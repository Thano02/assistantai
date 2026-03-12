"""
Service SMS via Twilio.
Envoi de confirmations et rappels de rendez-vous.
"""
from twilio.rest import Client as TwilioClient
from config import settings
from datetime import datetime
from typing import Optional
import pytz
from utils import get_logger

logger = get_logger(__name__)


def _get_twilio_creds(business_id: Optional[int]) -> tuple[str, str, str]:
    """Retourne (account_sid, auth_token, from_number) pour un business ou les creds globales."""
    if business_id:
        try:
            from database import SessionLocal, get_business_by_id
            db = SessionLocal()
            try:
                biz = get_business_by_id(db, business_id)
                if biz and biz.twilio_account_sid and biz.twilio_auth_token and biz.twilio_phone_number:
                    return biz.twilio_account_sid, biz.twilio_auth_token, biz.twilio_phone_number
            finally:
                db.close()
        except Exception:
            pass
    return settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_phone_number


def _get_business_address(business_id: Optional[int]) -> str:
    """Retourne l'adresse du business depuis la DB ou le config global."""
    if business_id:
        try:
            from database import SessionLocal, get_business_by_id
            db = SessionLocal()
            try:
                biz = get_business_by_id(db, business_id)
                if biz and biz.address:
                    return biz.address
            finally:
                db.close()
        except Exception:
            pass
    try:
        from config import load_business_config
        return load_business_config().get("address", "")
    except Exception:
        return ""


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
    business_id: Optional[int] = None,
) -> bool:
    """Envoie un SMS de confirmation après réservation."""
    dt_str = format_dt_fr(appointment_dt)
    address = _get_business_address(business_id)

    body = (
        f"✅ RDV confirmé !\n"
        f"📋 {service_name}\n"
        f"📅 {dt_str}\n"
    )
    if address:
        body += f"📍 {address}\n"
    body += f"\nPour annuler, répondez : ANNULER {reservation_id}"

    try:
        sid, token, from_num = _get_twilio_creds(business_id)
        TwilioClient(sid, token).messages.create(body=body, from_=from_num, to=to_number)
        return True
    except Exception as e:
        logger.error("[SMS] Erreur envoi confirmation: %s", e)
        return False


def send_reminder_sms(
    to_number: str,
    client_name: str,
    service_name: str,
    appointment_dt: datetime,
    reservation_id: int,
    business_id: Optional[int] = None,
) -> bool:
    """Envoie un SMS de rappel 24h avant le RDV."""
    dt_str = format_dt_fr(appointment_dt)
    address = _get_business_address(business_id)

    body = (
        f"⏰ Rappel RDV demain !\n"
        f"📋 {service_name}\n"
        f"📅 {dt_str}\n"
    )
    if address:
        body += f"📍 {address}\n"
    body += f"\nPour annuler, répondez : ANNULER {reservation_id}"

    try:
        sid, token, from_num = _get_twilio_creds(business_id)
        TwilioClient(sid, token).messages.create(body=body, from_=from_num, to=to_number)
        return True
    except Exception as e:
        logger.error("[SMS] Erreur envoi rappel: %s", e)
        return False


def send_cancellation_sms(
    to_number: str,
    service_name: str,
    appointment_dt: datetime,
    business_id: Optional[int] = None,
) -> bool:
    """Envoie un SMS de confirmation d'annulation."""
    dt_str = format_dt_fr(appointment_dt)
    body = (
        f"❌ Votre RDV a été annulé.\n"
        f"📋 {service_name} — {dt_str}\n\n"
        f"Pour reprendre RDV, appelez-nous !"
    )
    try:
        sid, token, from_num = _get_twilio_creds(business_id)
        TwilioClient(sid, token).messages.create(body=body, from_=from_num, to=to_number)
        return True
    except Exception as e:
        logger.error("[SMS] Erreur envoi annulation: %s", e)
        return False
