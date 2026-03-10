"""
Tracking de la consommation API par commerce.
Loggue chaque appel API avec son coût réel en EUR.
"""
from config import settings


def track_gpt_usage(business_id: int, input_tokens: int, output_tokens: int):
    """Loggue l'utilisation GPT-4o après un appel."""
    if not business_id:
        return
    from database import SessionLocal, log_usage
    cost_input = (input_tokens / 1000) * settings.cost_gpt4o_input_per_1k
    cost_output = (output_tokens / 1000) * settings.cost_gpt4o_output_per_1k
    db = SessionLocal()
    try:
        if input_tokens > 0:
            log_usage(db, business_id, "gpt_input", input_tokens, cost_input)
        if output_tokens > 0:
            log_usage(db, business_id, "gpt_output", output_tokens, cost_output)
    finally:
        db.close()


def track_tts_usage(business_id: int, char_count: int):
    """Loggue l'utilisation ElevenLabs TTS."""
    if not business_id:
        return
    from database import SessionLocal, log_usage
    cost = (char_count / 1000) * settings.cost_elevenlabs_per_1k_chars
    db = SessionLocal()
    try:
        log_usage(db, business_id, "tts_chars", char_count, cost)
    finally:
        db.close()


def track_voice_call(business_id: int, duration_minutes: float):
    """Loggue le coût d'un appel Twilio Voice."""
    if not business_id:
        return
    from database import SessionLocal, log_usage
    cost = duration_minutes * settings.cost_twilio_voice_per_min
    db = SessionLocal()
    try:
        log_usage(db, business_id, "twilio_voice_min", duration_minutes, cost)
    finally:
        db.close()


def track_sms(business_id: int, count: int = 1):
    """Loggue l'envoi d'un SMS Twilio."""
    if not business_id:
        return
    from database import SessionLocal, log_usage
    cost = count * settings.cost_twilio_sms
    db = SessionLocal()
    try:
        log_usage(db, business_id, "twilio_sms", count, cost)
    finally:
        db.close()
