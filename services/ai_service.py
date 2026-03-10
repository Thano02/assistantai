"""
Service IA — cerveau conversationnel du robot.
Utilise GPT-4o avec function calling pour orchestrer la conversation.
"""
import json
from datetime import datetime
from typing import Optional
from openai import OpenAI
import pytz

from config import settings
from database import (
    SessionLocal,
    get_or_create_client,
    get_upcoming_reservations,
    get_taken_slots,
    create_reservation,
    cancel_reservation,
    modify_reservation,
    update_client_name,
    get_business_by_id,
    get_employees,
    Reservation,
)
from services.slots_service import (
    get_available_slots,
    get_service_duration,
    parse_date_fr,
    format_slots_fr,
)
from services.sms_service import send_confirmation_sms, send_cancellation_sms
from services.calendar_service import (
    create_calendar_event,
    delete_calendar_event,
    update_calendar_event,
)
from services.faq_service import inject_faq_into_prompt
from utils import get_logger

logger = get_logger(__name__)
client_ai = OpenAI(api_key=settings.openai_api_key)

# ── Sessions en mémoire (call_sid → ConversationSession) ──────────────────
_sessions: dict[str, "ConversationSession"] = {}


class ConversationSession:
    def __init__(self, call_sid: str, caller_phone: str, business_id: int | None = None):
        self.call_sid = call_sid
        self.caller_phone = caller_phone
        self.business_id = business_id
        self.messages: list[dict] = []
        self.should_hangup = False
        self.pending_reservation: Optional[dict] = None
        self.reservation_info: Optional[dict] = None  # for email summary


def get_session(call_sid: str, caller_phone: str, business_id: int | None = None) -> ConversationSession:
    if call_sid not in _sessions:
        _sessions[call_sid] = ConversationSession(call_sid, caller_phone, business_id)
    return _sessions[call_sid]


def end_session(call_sid: str):
    _sessions.pop(call_sid, None)


# ── Prompt système ─────────────────────────────────────────────────────────

def _build_system_prompt(business_name: str, services_list: str, hours_list: str, address: str,
                          faq_block: str, has_employees: bool, employee_selection_enabled: bool) -> str:
    tz = pytz.timezone(settings.timezone)
    now_str = datetime.now(tz).strftime("%A %d %B %Y à %H:%M")

    employee_instruction = ""
    if has_employees and employee_selection_enabled:
        employee_instruction = (
            "\n8. Si le client n'a pas de préférence pour l'employé, utilise get_employees pour proposer "
            "les employés disponibles et demande au client s'il en préfère un en particulier."
        )

    return f"""Tu es la réceptionniste virtuelle de "{business_name}", situé au {address}.
Tu réponds uniquement en français, avec une voix chaleureuse, professionnelle et naturelle.
Nous sommes le {now_str}.

SERVICES PROPOSÉS:
{services_list}

HORAIRES D'OUVERTURE:
{hours_list}

TON RÔLE:
1. Identifier le client (son numéro est déjà connu — utilise get_client_info pour voir ses RDV).
2. S'il a un RDV à venir : proposer de modifier ou annuler.
3. Sinon : l'aider à réserver un nouveau RDV.
4. Vérifier les créneaux disponibles en temps réel (utilise check_available_slots).
5. Si le créneau souhaité est pris, proposer les 2-3 prochains disponibles.
6. Confirmer la réservation (utilise create_reservation ou modify_reservation).
7. Mettre fin à l'appel poliment avec end_call.{employee_instruction}

RÈGLES:
- Sois concis et clair — c'est un appel vocal, pas un chat.
- Ne répète pas ce que tu viens de dire.
- Si tu ne comprends pas, demande une clarification brève.
- Toujours confirmer les détails avant de valider (service, date, heure).
- Tu n'inventes jamais de créneau — utilise toujours check_available_slots.
- Appelle end_call uniquement quand la conversation est terminée.
- Si un client pose une question sur le commerce, réponds avec les infos de la FAQ.{faq_block}"""


# ── Outils GPT-4o ──────────────────────────────────────────────────────────

BASE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_client_info",
            "description": "Récupère les informations du client et ses réservations à venir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {"type": "string", "description": "Numéro E.164"}
                },
                "required": ["phone_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_available_slots",
            "description": "Vérifie les créneaux disponibles pour un service et une date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD ou 'demain', 'lundi'…"},
                    "service_name": {"type": "string"},
                    "employee_id": {"type": "integer", "description": "ID employé (optionnel)"},
                },
                "required": ["date", "service_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reservation",
            "description": "Crée une nouvelle réservation et envoie le SMS de confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {"type": "string"},
                    "service_name": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "time": {"type": "string", "description": "HH:MM"},
                    "client_name": {"type": "string"},
                    "employee_id": {"type": "integer", "description": "ID employé (optionnel)"},
                },
                "required": ["phone_number", "service_name", "date", "time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_reservation",
            "description": "Annule une réservation existante.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reservation_id": {"type": "integer"},
                    "phone_number": {"type": "string"},
                },
                "required": ["reservation_id", "phone_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify_reservation",
            "description": "Modifie la date/heure d'une réservation existante.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reservation_id": {"type": "integer"},
                    "phone_number": {"type": "string"},
                    "new_date": {"type": "string"},
                    "new_time": {"type": "string"},
                },
                "required": ["reservation_id", "phone_number", "new_date", "new_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": "Termine poliment l'appel après avoir confirmé la réservation ou répondu.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Message d'au revoir"}
                },
                "required": ["message"],
            },
        },
    },
]

EMPLOYEE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_employees",
        "description": "Liste les employés disponibles du commerce.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


# ── Exécution des outils ───────────────────────────────────────────────────

def _execute_tool(tool_name: str, args: dict, session: ConversationSession) -> str:
    caller_phone = session.caller_phone
    business_id = session.business_id
    db = SessionLocal()
    try:
        if tool_name == "get_client_info":
            phone = args["phone_number"]
            client = get_or_create_client(db, phone)
            reservations = get_upcoming_reservations(db, phone)
            result = {
                "name": client.name,
                "total_reservations": client.total_reservations,
                "upcoming_reservations": [
                    {
                        "id": r.id,
                        "service": r.service_name,
                        "datetime": r.appointment_dt.isoformat(),
                        "status": str(r.status),
                        "employee": r.employee_name,
                    }
                    for r in reservations
                ],
            }
            return json.dumps(result, ensure_ascii=False)

        elif tool_name == "get_employees":
            if not business_id:
                return json.dumps({"employees": []})
            employees = get_employees(db, business_id)
            return json.dumps({
                "employees": [{"id": e.id, "name": e.name, "specialty": e.specialty} for e in employees]
            }, ensure_ascii=False)

        elif tool_name == "check_available_slots":
            date_str = parse_date_fr(args["date"]) or args["date"]
            service = args["service_name"]
            duration = get_service_duration(service) or 30
            taken = get_taken_slots(db, date_str)
            slots = get_available_slots(taken, date_str, duration, max_slots=6)
            result = {
                "date": date_str,
                "service": service,
                "duration_minutes": duration,
                "available_slots": [s.isoformat() for s in slots],
                "available_slots_fr": format_slots_fr(slots),
            }
            return json.dumps(result, ensure_ascii=False)

        elif tool_name == "create_reservation":
            phone = args["phone_number"]
            service = args["service_name"]
            date_str = parse_date_fr(args["date"]) or args["date"]
            time_str = args["time"]
            client_name = args.get("client_name", "")
            employee_id = args.get("employee_id")

            tz = pytz.timezone(settings.timezone)
            appointment_dt = tz.localize(
                datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            )
            duration = get_service_duration(service) or 30

            if client_name:
                update_client_name(db, phone, client_name)

            # Resolve employee name
            employee_name = None
            if employee_id:
                employees = get_employees(db, business_id) if business_id else []
                emp = next((e for e in employees if e.id == employee_id), None)
                if emp:
                    employee_name = emp.name

            client_obj = get_or_create_client(db, phone)
            google_event_id = create_calendar_event(
                client_name or client_obj.name or phone,
                phone,
                service,
                appointment_dt,
                duration,
            )

            reservation = create_reservation(
                db, phone, service, appointment_dt, duration,
                google_event_id=google_event_id,
                employee_id=employee_id,
                employee_name=employee_name,
                business_id=business_id,
            )

            send_confirmation_sms(phone, client_name or "", service, appointment_dt, reservation.id)

            # Store for email summary
            session.reservation_info = {
                "service": service,
                "datetime": appointment_dt.strftime("%d/%m/%Y à %H:%M"),
                "employee": employee_name or "",
            }

            return json.dumps({
                "success": True,
                "reservation_id": reservation.id,
                "message": f"Réservation créée. SMS envoyé au {phone}.",
            }, ensure_ascii=False)

        elif tool_name == "cancel_reservation":
            reservation_id = args["reservation_id"]
            phone = args["phone_number"]

            res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
            if not res:
                return json.dumps({"success": False, "error": "Réservation introuvable"})

            google_event_id = res.google_event_id
            service = res.service_name
            appointment_dt = res.appointment_dt

            cancel_reservation(db, reservation_id)

            if google_event_id:
                delete_calendar_event(google_event_id)

            send_cancellation_sms(phone, service, appointment_dt)

            return json.dumps({
                "success": True,
                "message": "Réservation annulée. SMS d'annulation envoyé.",
            }, ensure_ascii=False)

        elif tool_name == "modify_reservation":
            reservation_id = args["reservation_id"]
            phone = args["phone_number"]
            new_date = parse_date_fr(args["new_date"]) or args["new_date"]
            new_time = args["new_time"]

            tz = pytz.timezone(settings.timezone)
            new_dt = tz.localize(
                datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M")
            )

            res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
            if not res:
                return json.dumps({"success": False, "error": "Réservation introuvable"})

            duration = res.duration_minutes
            modify_reservation(db, reservation_id, new_dt)

            if res.google_event_id:
                update_calendar_event(res.google_event_id, new_dt, duration)

            send_confirmation_sms(phone, "", res.service_name, new_dt, reservation_id)

            session.reservation_info = {
                "service": res.service_name,
                "datetime": new_dt.strftime("%d/%m/%Y à %H:%M"),
                "employee": res.employee_name or "",
            }

            return json.dumps({
                "success": True,
                "message": "Réservation modifiée. Nouveau SMS de confirmation envoyé.",
            }, ensure_ascii=False)

        elif tool_name == "end_call":
            return json.dumps({"action": "hangup", "message": args.get("message", "")})

        return json.dumps({"error": f"Outil inconnu: {tool_name}"})

    except Exception as e:
        logger.error("Erreur outil %s: %s", tool_name, e)
        return json.dumps({"error": str(e)})
    finally:
        db.close()


def _track_usage(business_id: int | None, response):
    """Track GPT-4o token usage for billing."""
    if not business_id:
        return
    try:
        from services.usage_tracker import track_gpt_usage
        usage = response.usage
        track_gpt_usage(business_id, usage.prompt_tokens, usage.completion_tokens)
    except Exception as e:
        logger.warning("Failed to track GPT usage: %s", e)


def _send_call_summary(session: ConversationSession):
    """Send call summary email to the business owner after end_call."""
    if not session.business_id:
        return
    try:
        from services.email_service import send_call_summary_email
        db = SessionLocal()
        try:
            business = get_business_by_id(db, session.business_id)
            if not business or not business.owner_email:
                return
            client = get_or_create_client(db, session.caller_phone)
            # Filter out system messages for the transcript
            transcript = [m for m in session.messages if m.get("role") in ("user", "assistant")]
            send_call_summary_email(
                email=business.owner_email,
                business_name=business.name,
                caller_phone=session.caller_phone,
                caller_name=client.name or "",
                transcript=transcript,
                reservation_info=session.reservation_info,
            )
        finally:
            db.close()
    except Exception as e:
        logger.warning("Failed to send call summary: %s", e)


# ── Point d'entrée principal ───────────────────────────────────────────────

def process_speech(
    call_sid: str,
    caller_phone: str,
    speech_text: str,
    business_id: int | None = None,
) -> tuple[str, bool]:
    """Traite le texte reconnu et retourne (réponse_texte, should_hangup)."""
    session = get_session(call_sid, caller_phone, business_id)

    # Build system prompt on first message
    if not session.messages:
        db = SessionLocal()
        try:
            faq_block = inject_faq_into_prompt(db, business_id) if business_id else ""
            has_employees = False
            employee_selection_enabled = False
            business_name = "notre établissement"
            address = ""
            services_str = "  - Consultation"
            hours_str = "  Lundi–Vendredi: 09:00 – 18:00"

            if business_id:
                business = get_business_by_id(db, business_id)
                if business:
                    business_name = business.name
                    employee_selection_enabled = business.employee_selection_enabled or False
                    employees = get_employees(db, business_id)
                    has_employees = len(employees) > 0

            # Try loading legacy business_config.json for services/hours
            try:
                from config import load_business_config
                bconfig = load_business_config()
                services_str = "\n".join(
                    f"  - {s['name']} ({s['duration']} min, {s['price']}€)"
                    for s in bconfig.get("services", [])
                )
                days_fr = {
                    "monday": "Lundi", "tuesday": "Mardi", "wednesday": "Mercredi",
                    "thursday": "Jeudi", "friday": "Vendredi", "saturday": "Samedi", "sunday": "Dimanche",
                }
                hours_lines = []
                for day_en, day_fr in days_fr.items():
                    h = bconfig.get("working_hours", {}).get(day_en)
                    if h:
                        hours_lines.append(f"  {day_fr}: {h['open']} – {h['close']}")
                    else:
                        hours_lines.append(f"  {day_fr}: Fermé")
                hours_str = "\n".join(hours_lines)
                address = bconfig.get("address", "")
                if not business_id:
                    business_name = bconfig.get("name", business_name)
            except Exception:
                pass

        finally:
            db.close()

        system_prompt = _build_system_prompt(
            business_name, services_str, hours_str, address,
            faq_block, has_employees, employee_selection_enabled,
        )
        session.messages.append({"role": "system", "content": system_prompt})

    session.messages.append({"role": "user", "content": speech_text})

    tools = BASE_TOOLS.copy()
    if session.business_id:
        db = SessionLocal()
        try:
            business = get_business_by_id(db, session.business_id)
            if business and business.employee_selection_enabled:
                tools.append(EMPLOYEE_TOOL)
        finally:
            db.close()

    # GPT-4o loop
    for _ in range(5):
        response = client_ai.chat.completions.create(
            model="gpt-4o",
            messages=session.messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.3,
        )
        _track_usage(session.business_id, response)

        msg = response.choices[0].message
        session.messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return msg.content or "Je suis désolée, pouvez-vous répéter ?", False

        should_hangup = False
        for tool_call in msg.tool_calls:
            fn_name = tool_call.function.name
            fn_args = json.loads(tool_call.function.arguments)
            tool_result = _execute_tool(fn_name, fn_args, session)

            session.messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result,
            })

            if fn_name == "end_call":
                should_hangup = True
                result_data = json.loads(tool_result)
                end_message = result_data.get("message", "Au revoir et à bientôt !")
                _send_call_summary(session)
                return end_message, True

    return "Je suis désolée, une erreur s'est produite. Veuillez rappeler.", False


def get_welcome_message(caller_phone: str, business_id: int | None = None) -> str:
    """Génère le message d'accueil personnalisé selon l'historique du client."""
    db = SessionLocal()
    try:
        business_name = "notre établissement"
        if business_id:
            business = get_business_by_id(db, business_id)
            if business:
                business_name = business.name
        else:
            try:
                from config import load_business_config
                business_name = load_business_config().get("name", business_name)
            except Exception:
                pass

        client = get_or_create_client(db, caller_phone)
        reservations = get_upcoming_reservations(db, caller_phone)

        tz = pytz.timezone(settings.timezone)
        jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        mois = [
            "janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre", "décembre",
        ]

        greeting = f"Bonjour {client.name} !" if client.name else "Bonjour !"

        if reservations:
            r = reservations[0]
            dt = r.appointment_dt
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt).astimezone(tz)
            else:
                dt = dt.astimezone(tz)
            dt_str = f"{jours[dt.weekday()]} {dt.day} {mois[dt.month - 1]} à {dt.strftime('%H:%M')}"
            emp_str = f" avec {r.employee_name}" if r.employee_name else ""
            return (
                f"{greeting} Vous êtes bien au {business_name}. "
                f"Je vois que vous avez un rendez-vous le {dt_str} pour {r.service_name}{emp_str}. "
                f"Souhaitez-vous le modifier, l'annuler, ou puis-je vous aider autrement ?"
            )
        else:
            return (
                f"{greeting} Vous êtes bien au {business_name}. "
                f"Comment puis-je vous aider ? Vous souhaitez prendre un rendez-vous ?"
            )
    finally:
        db.close()
