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
_SESSION_TTL_SECONDS = 3600  # 1 heure max par appel


class ConversationSession:
    def __init__(self, call_sid: str, caller_phone: str, business_id: int | None = None):
        self.call_sid = call_sid
        self.caller_phone = caller_phone
        self.business_id = business_id
        self.messages: list[dict] = []
        self.should_hangup = False
        self.reservation_info: Optional[dict] = None
        self.created_at: float = __import__('time').time()


def get_session(call_sid: str, caller_phone: str, business_id: int | None = None) -> ConversationSession:
    _evict_stale_sessions()
    if call_sid not in _sessions:
        _sessions[call_sid] = ConversationSession(call_sid, caller_phone, business_id)
    return _sessions[call_sid]


def end_session(call_sid: str):
    _sessions.pop(call_sid, None)


def _evict_stale_sessions():
    """Remove sessions older than TTL to prevent memory leaks."""
    import time
    now = time.time()
    stale = [sid for sid, s in _sessions.items() if now - s.created_at > _SESSION_TTL_SECONDS]
    for sid in stale:
        logger.info("Evicting stale session %s", sid)
        _sessions.pop(sid, None)


# ── Prompt système ─────────────────────────────────────────────────────────

def _build_system_prompt(business_name: str, services_list: str, hours_list: str, address: str,
                          faq_block: str, has_employees: bool, employee_selection_enabled: bool,
                          ai_description: str = "", profession_type: str = "salon") -> str:
    tz = pytz.timezone(settings.timezone)
    now_str = datetime.now(tz).strftime("%A %d %B %Y à %H:%M")

    employee_instruction = ""
    if has_employees and employee_selection_enabled:
        employee_instruction = (
            "\n8. Si le client n'a pas de préférence pour l'employé, utilise get_employees pour proposer "
            "les employés disponibles et demande au client s'il en préfère un en particulier."
        )

    description_block = ("\n\nCONTEXTE DU COMMERCE:\n" + ai_description) if ai_description else ""

    if profession_type == "restaurant":
        return f"""Tu es l'hôte(sse) d'accueil du restaurant "{business_name}".
Tu réponds uniquement en français, avec une voix chaleureuse et professionnelle.
Nous sommes le {now_str}.{description_block}

HORAIRES D'OUVERTURE:
{hours_list}

TON RÔLE:
1. Demander combien de personnes souhaitent réserver et pour quelle date/heure.
2. Vérifier les tables disponibles avec check_available_tables.
3. Proposer la table la plus adaptée (capacité = groupe ou légèrement supérieure).
4. Confirmer le nom du client (utilise get_client_info pour l'historique).
5. Réserver avec book_table.
6. Mettre fin à l'appel poliment avec end_call.

RÈGLES:
- Sois concis — c'est un appel vocal.
- Ne propose jamais une table sans avoir vérifié via check_available_tables.
- Toujours confirmer date, heure, nombre de personnes et nom avant de valider.
- En cas d'indisponibilité, propose d'autres créneaux.
- Appelle end_call uniquement quand la réservation est confirmée ou la conversation terminée.{faq_block}"""

    return f"""Tu es la réceptionniste virtuelle de "{business_name}", situé au {address}.
Tu réponds uniquement en français, avec une voix chaleureuse, professionnelle et naturelle.
Nous sommes le {now_str}.{description_block}

SERVICES PROPOSÉS:
{services_list}

HORAIRES D'OUVERTURE:
{hours_list}

SCRIPT DE LA CONVERSATION - ÉTAPE PAR ÉTAPE:
Le client a déjà dit bonjour. Tu enchaînes directement :
1. Appelle get_client_info pour voir ses RDV existants.
   → Si son nom est inconnu (null ou vide), demande : "Pouvez-vous me donner votre prénom et votre nom ?"
2. S'il confirme vouloir un RDV → demande quel SERVICE.
3. Quand tu as le service → demande quel JOUR (ex: "Pour quel jour souhaitez-vous ?")
4. Interprète les jours relatifs : "mardi" = le prochain mardi qui arrive, "demain" = demain, etc.
5. Quand tu as le jour → demande à quelle HEURE (ex: "À quelle heure vous conviendrait-il ?")
6. Quand tu as l'heure → vérifie avec check_available_slots.
7. Si le créneau exact est disponible → dis : "Parfait, je vous confirme un RDV [service] le [jour] à [heure] au nom de [prénom nom]. C'est bien ça ?"
8. Si le créneau n'est PAS disponible → propose exactement 2 créneaux : le plus proche AVANT et le plus proche APRÈS l'heure demandée. Ex: "Ce créneau n'est pas disponible. Je peux vous proposer 13h30 ou 14h30. Laquelle vous convient ?"
9. Si le client confirme → crée avec create_reservation (inclus client_name) puis appelle end_call.{employee_instruction}

RÈGLES IMPÉRATIVES:
- Pose UNE SEULE question à la fois — c'est un appel vocal, sois bref.
- N'invente aucun créneau — utilise toujours check_available_slots avant de proposer une heure.
- Ne demande jamais le numéro de téléphone — tu le connais déjà.
- Si le client dit "mardi" sans préciser la semaine, c'est TOUJOURS le prochain mardi.
- Toujours répéter service + date + heure complète avant de créer le RDV.
- Appelle end_call uniquement quand la réservation est confirmée ou la conversation terminée.
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

RESTAURANT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_available_tables",
            "description": "Vérifie quelles tables sont disponibles pour un nombre de personnes et un créneau.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD ou 'demain', 'lundi'…"},
                    "time": {"type": "string", "description": "HH:MM"},
                    "party_size": {"type": "integer", "description": "Nombre de personnes"},
                },
                "required": ["date", "time", "party_size"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_table",
            "description": "Réserve une table pour un groupe et envoie le SMS de confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {"type": "string"},
                    "client_name": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "time": {"type": "string", "description": "HH:MM"},
                    "party_size": {"type": "integer"},
                    "table_id": {"type": "integer", "description": "ID de la table choisie"},
                    "table_name": {"type": "string", "description": "Nom de la table"},
                },
                "required": ["phone_number", "date", "time", "party_size", "table_id", "table_name"],
            },
        },
    },
]


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
            duration = get_service_duration(service, business_id) or 30
            taken = get_taken_slots(db, date_str, business_id)
            slots = get_available_slots(taken, date_str, duration, business_id, max_slots=6)
            result = {
                "date": date_str,
                "service": service,
                "duration_minutes": duration,
                "available_slots": [s.isoformat() for s in slots],
                "available_slots_fr": format_slots_fr(slots),
            }
            logger.info("[Slots] business_id=%s date=%s service=%s duration=%d taken=%d available=%d",
                        business_id, date_str, service, duration, len(taken), len(slots))
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

            send_confirmation_sms(phone, client_name or "", service, appointment_dt, reservation.id, business_id)

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

            send_cancellation_sms(phone, service, appointment_dt, business_id)

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

            send_confirmation_sms(phone, "", res.service_name, new_dt, reservation_id, business_id)

            session.reservation_info = {
                "service": res.service_name,
                "datetime": new_dt.strftime("%d/%m/%Y à %H:%M"),
                "employee": res.employee_name or "",
            }

            return json.dumps({
                "success": True,
                "message": "Réservation modifiée. Nouveau SMS de confirmation envoyé.",
            }, ensure_ascii=False)

        elif tool_name == "check_available_tables":
            from database import get_available_tables
            date_str = parse_date_fr(args["date"]) or args["date"]
            time_str = args["time"]
            party_size = int(args["party_size"])
            tz = pytz.timezone(settings.timezone)
            dt = tz.localize(datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M"))
            tables = get_available_tables(db, business_id, dt, party_size)
            if not tables:
                return json.dumps({
                    "available": False,
                    "message": f"Aucune table disponible pour {party_size} personnes à {time_str} le {date_str}.",
                }, ensure_ascii=False)
            return json.dumps({
                "available": True,
                "tables": [{"id": t.id, "name": t.name, "capacity": t.capacity} for t in tables],
                "message": f"{len(tables)} table(s) disponible(s) pour {party_size} personnes.",
            }, ensure_ascii=False)

        elif tool_name == "book_table":
            from database import get_available_tables
            phone = args["phone_number"]
            client_name = args.get("client_name", "")
            date_str = parse_date_fr(args["date"]) or args["date"]
            time_str = args["time"]
            party_size = int(args["party_size"])
            table_id = int(args["table_id"])
            table_name = args["table_name"]
            tz = pytz.timezone(settings.timezone)
            appointment_dt = tz.localize(datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M"))

            if client_name:
                update_client_name(db, phone, client_name)

            reservation = create_reservation(
                db, phone,
                service_name=f"Réservation {party_size} pers.",
                appointment_dt=appointment_dt,
                duration_minutes=90,
                business_id=business_id,
                table_id=table_id,
                table_name=table_name,
                party_size=party_size,
            )

            send_confirmation_sms(phone, client_name, f"Table {table_name} ({party_size} pers.)", appointment_dt, reservation.id, business_id)
            session.reservation_info = {
                "service": f"Table {table_name} pour {party_size} personnes",
                "datetime": appointment_dt.strftime("%d/%m/%Y à %H:%M"),
                "employee": "",
            }
            return json.dumps({
                "success": True,
                "reservation_id": reservation.id,
                "message": f"Table {table_name} réservée pour {party_size} personnes. SMS envoyé.",
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

            ai_description = ""
            profession_type = "salon"
            if business_id:
                business = get_business_by_id(db, business_id)
                if business:
                    business_name = business.name
                    ai_description = business.ai_description or ""
                    profession_type = business.profession_type or "salon"
                    employee_selection_enabled = business.employee_selection_enabled or False
                    employees = get_employees(db, business_id)
                    has_employees = len(employees) > 0

            # Load services and hours: DB config first, then fallback to business_config.json
            import json as _json
            from services.slots_service import _get_services_for_business, _get_hours_for_business
            services_list = _get_services_for_business(business_id)
            if services_list:
                services_str = "\n".join(
                    f"  - {s['name']} ({s['duration']} min{', ' + str(s['price']) + '€' if s.get('price') else ''})"
                    for s in services_list
                )
            hours_map = _get_hours_for_business(business_id)
            days_fr = {
                "monday": "Lundi", "tuesday": "Mardi", "wednesday": "Mercredi",
                "thursday": "Jeudi", "friday": "Vendredi", "saturday": "Samedi", "sunday": "Dimanche",
            }
            if hours_map:
                hours_lines = []
                for day_en, day_fr in days_fr.items():
                    h = hours_map.get(day_en)
                    if h:
                        if "slots" in h:
                            slots_str = " / ".join(f"{s['open']}–{s['close']}" for s in h["slots"])
                        else:
                            slots_str = f"{h['open']}–{h['close']}"
                        hours_lines.append(f"  {day_fr}: {slots_str}")
                    else:
                        hours_lines.append(f"  {day_fr}: Fermé")
                hours_str = "\n".join(hours_lines)
            # Address from DB or fallback
            if business_id and business and business.address:
                address = business.address
            elif not address:
                try:
                    from config import load_business_config
                    address = load_business_config().get("address", "")
                except Exception:
                    pass

        finally:
            db.close()

        system_prompt = _build_system_prompt(
            business_name, services_str, hours_str, address,
            faq_block, has_employees, employee_selection_enabled,
            ai_description, profession_type,
        )
        session.messages.append({"role": "system", "content": system_prompt})

    session.messages.append({"role": "user", "content": speech_text})

    is_restaurant = False
    employee_selection_enabled_runtime = False
    if session.business_id:
        db2 = SessionLocal()
        try:
            biz = get_business_by_id(db2, session.business_id)
            if biz:
                is_restaurant = biz.profession_type == "restaurant"
                employee_selection_enabled_runtime = biz.employee_selection_enabled or False
        finally:
            db2.close()

    if is_restaurant:
        tools = [t for t in BASE_TOOLS if t["function"]["name"] not in ("check_available_slots",)] + RESTAURANT_TOOLS
    else:
        tools = BASE_TOOLS.copy()
        if employee_selection_enabled_runtime:
            tools.append(EMPLOYEE_TOOL)

    # GPT-4o-mini loop (faster, lower latency)
    for _ in range(5):
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
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
                f"{greeting} Bienvenue au {business_name}. "
                f"Je vois que vous avez un rendez-vous le {dt_str} pour {r.service_name}{emp_str}. "
                f"Souhaitez-vous le modifier, l'annuler, ou puis-je vous aider autrement ?"
            )
        else:
            return (
                f"{greeting} Bienvenue au {business_name}. "
                f"Souhaitez-vous prendre un rendez-vous ?"
            )
    finally:
        db.close()
