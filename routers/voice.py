"""
Voice webhooks using ElevenLabs Conversational AI + Twilio Media Streams.

Routes:
  POST /voice/{business_id}/incoming     → TwiML Connect to ElevenLabs ConvAI
  WS   /voice/{business_id}/ws           → WebSocket bridge Twilio ↔ ElevenLabs
  POST /voice/tools/check-slots          → Tool webhook: vérifier disponibilités
  POST /voice/tools/create-reservation   → Tool webhook: créer rendez-vous
  POST /voice/end                        → Twilio status callback (usage tracking)
"""
import json
import asyncio
from datetime import datetime
from typing import Optional

import websockets as ws_lib
from fastapi import APIRouter, Form, Response, WebSocket, WebSocketDisconnect, Request
from twilio.twiml.voice_response import VoiceResponse

from config import settings
from database import (
    SessionLocal, get_business_by_id, update_client_last_call,
    create_reservation, get_or_create_client, update_client_name,
)
from utils import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ── System prompt dynamique ────────────────────────────────────────────────────

def _build_system_prompt(business, caller_phone: str) -> str:
    import json as _json

    services_list = ""
    if business.services_json:
        try:
            svcs = _json.loads(business.services_json)
            services_list = "\n".join(
                f"- {s['name']} ({s.get('duration', 30)} min)" for s in svcs
            )
        except Exception:
            pass

    hours_list = ""
    if business.hours_json:
        try:
            hours = _json.loads(business.hours_json)
            day_fr = {
                "monday": "Lundi", "tuesday": "Mardi", "wednesday": "Mercredi",
                "thursday": "Jeudi", "friday": "Vendredi", "saturday": "Samedi", "sunday": "Dimanche",
            }
            for day_en, day_name in day_fr.items():
                h = hours.get(day_en, {})
                if isinstance(h, list):
                    slots_str = ", ".join(f"{s['open']}-{s['close']}" for s in h if s.get("open"))
                    hours_list += f"\n{day_name}: {slots_str if slots_str else 'Fermé'}"
                elif h and h.get("open"):
                    hours_list += f"\n{day_name}: {h['open']} - {h['close']}"
                else:
                    hours_list += f"\n{day_name}: Fermé"
        except Exception:
            pass

    address = business.address or ""
    today = datetime.now().strftime("%A %d %B %Y")
    bid = business.id

    return f"""Tu es la réceptionniste virtuelle de "{business.name}"{f", situé au {address}" if address else ""}.
Tu parles UNIQUEMENT en français, de façon naturelle et concise (1-2 phrases maximum).

INFORMATIONS APPEL:
- Aujourd'hui: {today}
- Numéro de l'appelant: {caller_phone}
- business_id: {bid} — OBLIGATOIRE: inclus ce numéro dans CHAQUE appel d'outil sans exception.

SERVICES PROPOSÉS:
{services_list or "À préciser"}

HORAIRES:
{hours_list or "À préciser"}

DÉROULÉ:
1. Demande quel service le client souhaite (liste les options disponibles)
2. Si l'heure n'est pas précisée, demande-la
3. Vérifie la disponibilité avec check_available_slots
4. Si le créneau n'est pas dispo → propose 1 créneau juste avant et 1 juste après
5. Si le nom du client est inconnu → demande prénom et nom
6. Confirme le RDV oralement avant de créer
7. Crée le RDV avec create_reservation (inclus toujours business_id={bid})
8. Dis au revoir chaleureusement

RÈGLES:
- Ne propose jamais plus de 2 créneaux à la fois
- Réponds en 1-2 phrases maximum
- Ne mentionne jamais le business_id au client"""


# ── Incoming call → TwiML Media Stream ────────────────────────────────────────

@router.post("/{business_id}/incoming")
async def voice_incoming(
    business_id: int,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: Optional[str] = Form(None),
):
    db = SessionLocal()
    try:
        business = get_business_by_id(db, business_id)
        if not business or not business.is_active or not business.subscription_paid:
            resp = VoiceResponse()
            resp.say(
                "Ce service est temporairement indisponible. Veuillez rappeler plus tard.",
                language="fr-FR",
            )
            resp.hangup()
            return Response(content=str(resp), media_type="application/xml")
        update_client_last_call(db, From)
    finally:
        db.close()

    base = settings.base_url.replace("https://", "").replace("http://", "").rstrip("/")
    ws_url = f"wss://{base}/voice/{business_id}/ws"

    resp = VoiceResponse()
    connect = resp.connect()
    connect.stream(url=ws_url, custom_parameters={"caller": From, "call_sid": CallSid})
    return Response(content=str(resp), media_type="application/xml")


# ── WebSocket bridge Twilio ↔ ElevenLabs ConvAI ────────────────────────────────

@router.websocket("/{business_id}/ws")
async def voice_ws(websocket: WebSocket, business_id: int):
    await websocket.accept()

    stream_sid = None
    caller = "unknown"

    el_url = (
        f"wss://api.elevenlabs.io/v1/convai/conversation"
        f"?agent_id={settings.elevenlabs_agent_id}"
    )

    try:
        async with ws_lib.connect(
            el_url,
            additional_headers={"xi-api-key": settings.elevenlabs_api_key},
        ) as el_ws:

            # Lire les premiers messages Twilio pour récupérer stream_sid et caller
            for _ in range(3):
                try:
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
                    data = json.loads(raw)
                    event = data.get("event")
                    if event == "start":
                        stream_sid = data["start"]["streamSid"]
                        caller = data["start"].get("customParameters", {}).get("caller", "unknown")
                        break
                except asyncio.TimeoutError:
                    break
                except Exception:
                    break

            # Charger le contexte business
            db = SessionLocal()
            try:
                business = get_business_by_id(db, business_id)
                if not business:
                    await websocket.close()
                    return
                system_prompt = _build_system_prompt(business, caller)
                business_name = business.name
                voice_id = business.elevenlabs_voice_id or settings.elevenlabs_voice_id
            finally:
                db.close()

            # Initialiser la conversation ElevenLabs
            await el_ws.send(json.dumps({
                "type": "conversation_initiation_client_data",
                "conversation_config_override": {
                    "agent": {
                        "prompt": {"prompt": system_prompt},
                        "first_message": (
                            f"Bonjour, vous êtes bien chez {business_name}, "
                            f"je suis votre assistant vocal. Comment puis-je vous aider ?"
                        ),
                    },
                    "tts": {"voice_id": voice_id},
                },
            }))

            async def twilio_to_el():
                try:
                    while True:
                        msg = await websocket.receive_text()
                        data = json.loads(msg)
                        event = data.get("event")
                        if event == "media":
                            await el_ws.send(json.dumps({
                                "user_audio_chunk": data["media"]["payload"]
                            }))
                        elif event == "stop":
                            break
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    logger.error("[WS] twilio→el error: %s", e)

            async def el_to_twilio():
                try:
                    async for raw in el_ws:
                        data = json.loads(raw)
                        t = data.get("type")
                        if t == "audio":
                            audio = data.get("audio_event", {}).get("audio_base_64")
                            if audio and stream_sid:
                                await websocket.send_json({
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {"payload": audio},
                                })
                        elif t == "interruption":
                            if stream_sid:
                                await websocket.send_json({
                                    "event": "clear",
                                    "streamSid": stream_sid,
                                })
                        elif t == "agent_response":
                            txt = data.get("agent_response_event", {}).get("agent_response", "")
                            if txt:
                                logger.info("[ConvAI] Agent: %s", txt[:120])
                        elif t == "user_transcript":
                            txt = data.get("user_transcription_event", {}).get("user_transcript", "")
                            if txt:
                                logger.info("[ConvAI] User: %s", txt[:120])
                except Exception as e:
                    logger.error("[WS] el→twilio error: %s", e)

            await asyncio.gather(twilio_to_el(), el_to_twilio())

    except Exception as e:
        logger.error("[WS] Bridge error business_id=%d: %s", business_id, e)
    finally:
        try:
            from services.usage_tracker import track_voice_call
            track_voice_call(business_id, 1)
        except Exception:
            pass


# ── Tool webhooks ──────────────────────────────────────────────────────────────

@router.post("/tools/check-slots")
async def tool_check_slots(request: Request):
    body = await request.json()
    params = body.get("parameters", body)
    logger.info("[Tool] check-slots raw: %s", params)

    date_str = params.get("date", "")
    time_str = params.get("time", "")
    service_name = params.get("service_name", "")
    try:
        business_id = int(params.get("business_id", 0))
    except (TypeError, ValueError):
        business_id = 0

    from services.slots_service import get_available_slots, parse_date_fr, format_slots_fr, get_service_duration

    resolved = parse_date_fr(date_str)
    if not resolved:
        return {"result": f"Je n'ai pas compris la date '{date_str}'. Pouvez-vous préciser ?"}

    duration = get_service_duration(service_name, business_id) or 30
    slots = get_available_slots(resolved, duration, business_id)

    if not slots:
        return {"result": f"Aucun créneau disponible le {date_str} pour {service_name}."}

    # Si heure préférée → propose avant/après
    if time_str:
        try:
            parts = time_str.replace("h", ":").replace("H", ":").split(":")
            hour = int(parts[0])
            minute = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else 0
            from datetime import time as time_type
            target = time_type(hour, minute)

            before = [s for s in slots if s.time() < target]
            after = [s for s in slots if s.time() >= target]
            exact = [s for s in slots if s.hour == hour and s.minute == minute]

            def _fmt(s):
                return f"{s.hour}h{s.strftime('%M') if s.minute else '00'}"

            if exact:
                return {"result": f"Le créneau {_fmt(exact[0])} est disponible. Souhaitez-vous confirmer ?"}

            suggestions = []
            if before:
                suggestions.append(_fmt(before[-1]))
            if after:
                suggestions.append(_fmt(after[0]))

            if suggestions:
                opts = " et ".join(suggestions)
                return {"result": f"Le créneau {time_str} n'est pas disponible. Je peux vous proposer {opts}. Lequel vous convient ?"}
        except Exception:
            pass

    # Pas d'heure → liste les 5 premiers créneaux
    formatted = format_slots_fr(slots[:5])
    return {"result": f"Créneaux disponibles le {date_str} pour {service_name} : {formatted}. Lequel souhaitez-vous ?"}


@router.post("/tools/create-reservation")
async def tool_create_reservation(request: Request):
    body = await request.json()
    params = body.get("parameters", body)
    logger.info("[Tool] create-reservation raw: %s", params)

    date_str = params.get("date", "")
    time_str = params.get("time", "")
    service_name = params.get("service_name", "")
    client_name = params.get("client_name", "").strip()
    phone_number = params.get("phone_number", "").strip()
    try:
        business_id = int(params.get("business_id", 0))
    except (TypeError, ValueError):
        business_id = 0

    from services.slots_service import parse_date_fr, get_service_duration
    from services.sms_service import send_confirmation_sms

    resolved = parse_date_fr(date_str)
    if not resolved:
        return {"result": f"Erreur : impossible de comprendre la date '{date_str}'."}

    try:
        parts = time_str.replace("h", ":").replace("H", ":").split(":")
        hour = int(parts[0])
        minute = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else 0
        appointment_dt = datetime.strptime(resolved, "%Y-%m-%d").replace(hour=hour, minute=minute)
    except Exception:
        return {"result": f"Erreur : impossible de comprendre l'heure '{time_str}'."}

    duration = get_service_duration(service_name, business_id) or 30

    db = SessionLocal()
    try:
        reservation = create_reservation(
            db, phone_number, service_name, appointment_dt, duration,
            business_id=business_id,
        )
        if client_name:
            update_client_name(db, phone_number, client_name)

        # SMS confirmation
        if phone_number:
            try:
                send_confirmation_sms(
                    phone_number, client_name, service_name,
                    appointment_dt, reservation.id, business_id,
                )
            except Exception as se:
                logger.error("[Tool] SMS error: %s", se)

        # Sync calendrier
        business = get_business_by_id(db, business_id)
        if business and (business.google_access_token or business.outlook_access_token):
            try:
                from services.calendar_service import create_calendar_event
                create_calendar_event(
                    summary=f"{service_name} — {client_name or phone_number}",
                    start_dt=appointment_dt,
                    duration_minutes=duration,
                    description=f"RDV pris par téléphone\nClient: {client_name}\nTél: {phone_number}",
                    business=business,
                )
            except Exception as ce:
                logger.error("[Tool] Calendar sync error: %s", ce)

    except Exception as e:
        logger.error("[Tool] create_reservation error: %s", e)
        return {"result": "Une erreur est survenue. Veuillez rappeler pour confirmer votre rendez-vous."}
    finally:
        db.close()

    day_fr = appointment_dt.strftime("%d/%m/%Y")
    hour_fmt = f"{appointment_dt.hour}h{appointment_dt.strftime('%M') if appointment_dt.minute else '00'}"
    return {
        "result": (
            f"Parfait {client_name + ' !' if client_name else '!'} "
            f"Votre rendez-vous pour {service_name} est confirmé le {day_fr} à {hour_fmt}. "
            f"Vous recevrez un SMS de confirmation. À bientôt !"
        )
    }


# ── Status callback fin d'appel ────────────────────────────────────────────────

@router.post("/end")
def voice_end(
    CallSid: str = Form(...),
    CallStatus: Optional[str] = Form(None),
    CallDuration: Optional[str] = Form(None),
):
    logger.info("[Voice] end CallSid=%s status=%s duration=%s", CallSid, CallStatus, CallDuration)
    return {"status": "ok"}
