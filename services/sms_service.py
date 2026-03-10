"""
Service SMS via Twilio.
Envoi de confirmations et rappels de rendez-vous.
"""
from twilio.rest import Client as TwilioClient
from config import settings
from config import load_business_config
from datetime import datetime
import pytz


def _twilio_client() -> TwilioClient:
    return TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)


def format_dt_fr(dt: datetime) -> str:
    """Formate une datetime en heure locale lisible en français."""
    tz = pytz.timezone(settings.timezone)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt).astimezone(tz)
    else:
        dt = dt.astimezone(tz)

    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois = [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ]
    return f"{jours[dt.weekday()]} {dt.day} {mois[dt.month - 1]} à {dt.strftime('%H:%M')}"


def send_confirmation_sms(
    to_number: str,
    client_name: str,
    service_name: str,
    appointment_dt: datetime,
    reservation_id: int,
) -> bool:
    """Envoie un SMS de confirmation après réservation."""
    business = load_business_config()
    dt_str = format_dt_fr(appointment_dt)

    body = (
        f"✅ RDV confirmé !\n"
        f"📋 {service_name}\n"
        f"📅 {dt_str}\n"
        f"📍 {business['address']}\n\n"
        f"Pour annuler, répondez : ANNULER {reservation_id}"
    )

    try:
        client = _twilio_client()
        client.messages.create(
            body=body,
            from_=settings.twilio_phone_number,
            to=to_number,
        )
        return True
    except Exception as e:
        print(f"[SMS] Erreur envoi confirmation: {e}")
        return False


def send_reminder_sms(
    to_number: str,
    client_name: str,
    service_name: str,
    appointment_dt: datetime,
    reservation_id: int,
) -> bool:
    """Envoie un SMS de rappel 24h avant le RDV."""
    business = load_business_config()
    dt_str = format_dt_fr(appointment_dt)

    body = (
        f"⏰ Rappel RDV demain !\n"
        f"📋 {service_name}\n"
        f"📅 {dt_str}\n"
        f"📍 {business['address']}\n\n"
        f"Pour annuler, répondez : ANNULER {reservation_id}"
    )

    try:
        client = _twilio_client()
        client.messages.create(
            body=body,
            from_=settings.twilio_phone_number,
            to=to_number,
        )
        return True
    except Exception as e:
        print(f"[SMS] Erreur envoi rappel: {e}")
        return False


def send_cancellation_sms(
    to_number: str,
    service_name: str,
    appointment_dt: datetime,
) -> bool:
    """Envoie un SMS de confirmation d'annulation."""
    dt_str = format_dt_fr(appointment_dt)
    body = (
        f"❌ Votre RDV a été annulé.\n"
        f"📋 {service_name} — {dt_str}\n\n"
        f"Pour reprendre RDV, appelez-nous !"
    )
    try:
        client = _twilio_client()
        client.messages.create(
            body=body,
            from_=settings.twilio_phone_number,
            to=to_number,
        )
        return True
    except Exception as e:
        print(f"[SMS] Erreur envoi annulation: {e}")
        return False
