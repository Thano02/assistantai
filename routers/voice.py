"""
Webhooks Twilio pour les appels vocaux (multi-tenant + fallback global).

Routes:
  POST /voice/incoming              → appel sans business_id (legacy)
  POST /voice/{business_id}/incoming → appel multi-tenant
"""
from fastapi import APIRouter, Form, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from typing import Optional

from services.ai_service import process_speech, get_welcome_message, get_session, end_session
from services.tts_service import text_to_speech
from database import SessionLocal, update_client_last_call, get_business_by_id, get_business_by_twilio_number
from utils import get_logger

logger = get_logger(__name__)
router = APIRouter()

GATHER_TIMEOUT = 5
GATHER_SPEECH_TIMEOUT = 2


# ── TwiML helpers ──────────────────────────────────────────────────────────────

def _get_voice_id(business_id: int | None) -> str | None:
    """Retourne le voice_id ElevenLabs du business, ou None pour utiliser le global."""
    if not business_id:
        return None
    db = SessionLocal()
    try:
        business = get_business_by_id(db, business_id)
        return business.elevenlabs_voice_id if business else None
    finally:
        db.close()


def _twiml_response(text: str, action_url: str, voice_id: str = None) -> str:
    """TwiML avec audio ElevenLabs + Gather pour la prochaine parole."""
    audio_url = text_to_speech(text, voice_id)
    response = VoiceResponse()
    gather = Gather(
        input="speech",
        action=action_url,
        method="POST",
        language="fr-FR",
        speech_timeout=str(GATHER_SPEECH_TIMEOUT),
        timeout=str(GATHER_TIMEOUT),
        action_on_empty_result=True,
    )
    gather.play(audio_url)
    response.append(gather)
    no_input_url = action_url.replace("/process", "/no-input")
    response.redirect(no_input_url, method="POST")
    return str(response)


def _twiml_hangup(text: str, voice_id: str = None) -> str:
    """TwiML avec message d'au revoir puis raccroche."""
    audio_url = text_to_speech(text, voice_id)
    response = VoiceResponse()
    response.play(audio_url)
    response.hangup()
    return str(response)


def _twiml_unavailable() -> str:
    response = VoiceResponse()
    response.say(
        "Ce service est temporairement indisponible. Veuillez rappeler plus tard. Merci.",
        language="fr-FR",
    )
    response.hangup()
    return str(response)


# ── Core handlers (shared logic) ───────────────────────────────────────────────

def _handle_incoming(call_sid: str, caller_phone: str, base_process_url: str,
                     business_id: int | None = None) -> Response:
    voice_id = None
    db = SessionLocal()
    try:
        if business_id:
            business = get_business_by_id(db, business_id)
            if not business or not business.is_active:
                return Response(content=_twiml_unavailable(), media_type="application/xml")
            if not business.subscription_paid:
                return Response(content=_twiml_unavailable(), media_type="application/xml")
            voice_id = business.elevenlabs_voice_id
            logger.info(f"[Voice] business_id={business_id} elevenlabs_voice_id={voice_id!r}")
        update_client_last_call(db, caller_phone)
    finally:
        db.close()

    welcome_text = get_welcome_message(caller_phone, business_id)
    twiml = _twiml_response(welcome_text, base_process_url, voice_id)
    return Response(content=twiml, media_type="application/xml")


def _handle_process(call_sid: str, caller_phone: str, speech: str,
                    process_url: str, no_input_url: str,
                    business_id: int | None = None) -> Response:
    voice_id = _get_voice_id(business_id)

    if not speech:
        audio_url = text_to_speech("Je n'ai pas entendu votre réponse. Pouvez-vous répéter ?", voice_id)
        response = VoiceResponse()
        gather = Gather(
            input="speech", action=process_url, method="POST",
            language="fr-FR",
            speech_timeout=str(GATHER_SPEECH_TIMEOUT), timeout=str(GATHER_TIMEOUT),
        )
        gather.play(audio_url)
        response.append(gather)
        response.redirect(no_input_url, method="POST")
        return Response(content=str(response), media_type="application/xml")

    reply_text, should_hangup = process_speech(call_sid, caller_phone, speech, business_id)

    if should_hangup:
        twiml = _twiml_hangup(reply_text, voice_id)
        end_session(call_sid)
    else:
        twiml = _twiml_response(reply_text, process_url, voice_id)

    return Response(content=twiml, media_type="application/xml")


def _handle_no_input(call_sid: str, caller_phone: str,
                     process_url: str, no_input_url: str,
                     business_id: int | None = None) -> Response:
    voice_id = _get_voice_id(business_id)
    session = get_session(call_sid, caller_phone)
    count = getattr(session, "_no_input_count", 0) + 1
    session._no_input_count = count

    if count >= 2:
        end_session(call_sid)
        return Response(
            content=_twiml_hangup("Je ne vous entends pas. N'hésitez pas à rappeler. Au revoir !", voice_id),
            media_type="application/xml",
        )

    audio_url = text_to_speech("Je ne vous entends pas bien. Pouvez-vous parler directement dans le téléphone ?", voice_id)
    response = VoiceResponse()
    gather = Gather(
        input="speech", action=process_url, method="POST",
        language="fr-FR",
        speech_timeout=str(GATHER_SPEECH_TIMEOUT), timeout=str(GATHER_TIMEOUT),
    )
    gather.play(audio_url)
    response.append(gather)
    response.redirect(no_input_url, method="POST")
    return Response(content=str(response), media_type="application/xml")


# ── Routes globales (legacy / sans business_id) ───────────────────────────────

@router.post("/incoming")
def voice_incoming(
    CallSid: str = Form(...),
    From: str = Form(...),
    To: Optional[str] = Form(None),
):
    # Auto-detect business from the Twilio number that was called
    business_id = None
    logger.info("[Voice] incoming call From=%s To=%s", From, To)
    if To:
        db = SessionLocal()
        try:
            # Log all stored numbers for debug
            from database import Business as _B
            stored = [(b.id, b.name, b.twilio_phone_number) for b in db.query(_B).filter(_B.twilio_phone_number.isnot(None)).all()]
            logger.info("[Voice] stored twilio numbers: %s", stored)
            business = get_business_by_twilio_number(db, To)
            if business:
                logger.info("[Voice] found business id=%d name=%s active=%s paid=%s", business.id, business.name, business.is_active, business.subscription_paid)
            else:
                logger.warning("[Voice] no business found for To=%s", To)
            if business and business.is_active and business.subscription_paid:
                business_id = business.id
                logger.info("[Voice] Auto-detected business_id=%d from To=%s", business_id, To)
        finally:
            db.close()

    if business_id:
        process_url = f"/voice/{business_id}/process"
        return _handle_incoming(CallSid, From, process_url, business_id)
    return _handle_incoming(CallSid, From, "/voice/process")


@router.post("/process")
def voice_process(
    SpeechResult: Optional[str] = Form(None),
    CallSid: str = Form(...),
    From: str = Form(...),
):
    return _handle_process(CallSid, From, (SpeechResult or "").strip(),
                           "/voice/process", "/voice/no-input")


@router.post("/no-input")
def voice_no_input(
    CallSid: str = Form(...),
    From: str = Form(...),
):
    return _handle_no_input(CallSid, From, "/voice/process", "/voice/no-input")


@router.post("/end")
def voice_end(
    CallSid: str = Form(...),
    CallStatus: Optional[str] = Form(None),
    CallDuration: Optional[str] = Form(None),
):
    """Webhook fin d'appel (statusCallback)."""
    if CallDuration:
        try:
            db = SessionLocal()
            from services.usage_tracker import track_voice_call
            session = get_session(CallSid, "")
            if session.business_id:
                minutes = max(1, round(int(CallDuration) / 60))
                track_voice_call(session.business_id, minutes)
        except Exception:
            pass
        finally:
            try:
                db.close()
            except Exception:
                pass
    end_session(CallSid)
    return {"status": "ok"}


# ── Routes multi-tenant ───────────────────────────────────────────────────────

@router.post("/{business_id}/incoming")
def voice_incoming_tenant(
    business_id: int,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: Optional[str] = Form(None),
):
    process_url = f"/voice/{business_id}/process"
    return _handle_incoming(CallSid, From, process_url, business_id)


@router.post("/{business_id}/process")
def voice_process_tenant(
    business_id: int,
    SpeechResult: Optional[str] = Form(None),
    CallSid: str = Form(...),
    From: str = Form(...),
):
    process_url = f"/voice/{business_id}/process"
    no_input_url = f"/voice/{business_id}/no-input"
    return _handle_process(CallSid, From, (SpeechResult or "").strip(),
                           process_url, no_input_url, business_id)


@router.post("/{business_id}/no-input")
def voice_no_input_tenant(
    business_id: int,
    CallSid: str = Form(...),
    From: str = Form(...),
):
    process_url = f"/voice/{business_id}/process"
    no_input_url = f"/voice/{business_id}/no-input"
    return _handle_no_input(CallSid, From, process_url, no_input_url, business_id)
