"""
Appel démo — initie un appel Twilio sortant vers un prospect.
POST /demo/call   → lance l'appel
GET  /demo/twiml  → TwiML servi à Twilio pendant l'appel
"""
from fastapi import APIRouter, Form, Response
from fastapi.responses import JSONResponse
from twilio.twiml.voice_response import VoiceResponse

from config import settings
from services.tts_service import text_to_speech
from utils import get_logger

logger = get_logger(__name__)
router = APIRouter()

DEMO_SCRIPT = (
    "Bonjour ! Je suis votre assistant vocal IA, propulsé par AssistantAI. "
    "Je suis capable de répondre aux appels de vos clients, prendre leurs rendez-vous "
    "vingt-quatre heures sur vingt-quatre, sept jours sur sept, "
    "envoyer des confirmations par SMS, et synchroniser tout ça dans votre calendrier, "
    "de manière totalement automatique. "
    "Imaginez : votre client appelle pendant que vous êtes occupé, "
    "et moi je m'occupe de tout. Plus aucun rendez-vous manqué. "
    "Pour découvrir AssistantAI et créer votre compte, rendez-vous sur notre site. "
    "À très bientôt !"
)


@router.post("/call")
def demo_call(phone: str = Form(...)):
    """Lance un appel Twilio sortant vers le numéro fourni."""
    if not settings.twilio_account_sid or not settings.twilio_phone_number:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "message": "Service d'appel non configuré."},
        )

    # Validation basique du numéro
    clean = phone.strip().replace(" ", "").replace("-", "")
    if not clean.startswith("+") or len(clean) < 8:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Numéro invalide. Format : +33612345678"},
        )

    try:
        from twilio.rest import Client
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        call = client.calls.create(
            to=clean,
            from_=settings.twilio_phone_number,
            url=f"{settings.base_url}/demo/twiml",
            method="GET",
        )
        logger.info("Demo call initiated to %s — SID %s", clean, call.sid)
        return JSONResponse(content={"status": "ok", "message": "Appel en cours, vous allez être appelé dans quelques secondes !"})
    except Exception as e:
        logger.error("Demo call error: %s", e)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Impossible d'initier l'appel. Vérifiez votre numéro."},
        )


@router.get("/twiml")
def demo_twiml():
    """TwiML joué lors de l'appel démo."""
    try:
        audio_url = text_to_speech(DEMO_SCRIPT)
        response = VoiceResponse()
        response.play(audio_url)
        response.hangup()
    except Exception as e:
        logger.error("Demo TwiML TTS error: %s", e)
        response = VoiceResponse()
        response.say(DEMO_SCRIPT, language="fr-FR")
        response.hangup()
    return Response(content=str(response), media_type="application/xml")
