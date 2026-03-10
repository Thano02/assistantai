"""Mailgun transactional email service."""
import requests
from datetime import datetime
from config import settings
from utils import get_logger

logger = get_logger(__name__)


def _send(to: str, subject: str, html: str) -> bool:
    if not settings.mailgun_enabled:
        logger.warning("Mailgun not configured — skipping email to %s", to)
        return False

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.mailgun_domain}/messages",
            auth=("api", settings.mailgun_api_key),
            data={
                "from": f"{settings.from_name} <{settings.from_email}>",
                "to": to,
                "subject": subject,
                "html": html,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Email sent to %s: %s", to, subject)
            return True
        logger.error("Mailgun error %s: %s", resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.error("Email send failed: %s", e)
        return False


# ── Email verification ────────────────────────────────────────────────────────

def send_verification_email(email: str, token: str, business_name: str) -> bool:
    verify_url = f"{settings.base_url}/auth/verify-email?token={token}"
    html = f"""
    <div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;padding:40px 20px">
      <h2 style="color:#1a1a2e;margin-bottom:8px">Bienvenue sur AssistantAI 👋</h2>
      <p style="color:#6b7280;margin-bottom:24px">
        Merci de vous être inscrit avec le commerce <strong>{business_name}</strong>.
        Cliquez sur le bouton ci-dessous pour confirmer votre adresse e-mail.
      </p>
      <a href="{verify_url}"
         style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;
                padding:14px 28px;border-radius:10px;font-weight:600;font-size:15px">
        Confirmer mon adresse e-mail
      </a>
      <p style="color:#9ca3af;font-size:12px;margin-top:32px">
        Ce lien expire dans 24 heures. Si vous n'avez pas créé de compte, ignorez cet e-mail.
      </p>
    </div>
    """
    return _send(email, "Confirmez votre adresse e-mail — AssistantAI", html)


def send_welcome_email(email: str, business_name: str) -> bool:
    html = f"""
    <div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;padding:40px 20px">
      <h2 style="color:#1a1a2e;margin-bottom:8px">Votre compte est activé ! 🎉</h2>
      <p style="color:#6b7280;margin-bottom:24px">
        Bonjour, votre compte <strong>{business_name}</strong> est maintenant actif.
        Connectez votre numéro Twilio et votre calendrier pour commencer à recevoir des réservations.
      </p>
      <a href="{settings.base_url}/dashboard"
         style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;
                padding:14px 28px;border-radius:10px;font-weight:600;font-size:15px">
        Accéder au dashboard
      </a>
    </div>
    """
    return _send(email, f"Bienvenue sur AssistantAI, {business_name} !", html)


# ── Call summary ──────────────────────────────────────────────────────────────

def send_call_summary_email(
    email: str,
    business_name: str,
    caller_phone: str,
    caller_name: str,
    transcript: list[dict],
    reservation_info: dict | None,
) -> bool:
    now_str = datetime.now().strftime("%d/%m/%Y à %H:%M")

    transcript_html = ""
    for msg in transcript:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            label = "Client"
            color = "#374151"
            bg = "#f3f4f6"
        elif role == "assistant":
            label = "Robot"
            color = "#1d4ed8"
            bg = "#eff6ff"
        else:
            continue
        transcript_html += f"""
        <div style="margin-bottom:8px;padding:10px 14px;border-radius:8px;background:{bg}">
          <span style="font-size:11px;font-weight:600;color:#9ca3af;text-transform:uppercase">{label}</span>
          <p style="margin:4px 0 0;color:{color};font-size:14px">{content}</p>
        </div>"""

    reservation_block = ""
    if reservation_info:
        service = reservation_info.get("service", "—")
        dt = reservation_info.get("datetime", "—")
        employee = reservation_info.get("employee", "")
        emp_line = f"<br><strong>Employé :</strong> {employee}" if employee else ""
        reservation_block = f"""
        <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:10px;padding:16px;margin-bottom:24px">
          <p style="margin:0;font-weight:600;color:#16a34a">✅ RDV confirmé</p>
          <p style="margin:6px 0 0;color:#374151;font-size:14px">
            <strong>Service :</strong> {service}<br>
            <strong>Date :</strong> {dt}{emp_line}
          </p>
        </div>"""

    html = f"""
    <div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;padding:40px 20px">
      <h2 style="color:#1a1a2e;margin-bottom:4px">Résumé d'appel</h2>
      <p style="color:#9ca3af;font-size:13px;margin-bottom:24px">{now_str} · Appelant : {caller_name or caller_phone}</p>
      {reservation_block}
      <h3 style="color:#374151;font-size:15px;margin-bottom:12px">Transcription</h3>
      {transcript_html}
      <p style="color:#9ca3af;font-size:12px;margin-top:32px">
        — AssistantAI · <a href="{settings.base_url}/dashboard" style="color:#2563eb">Voir le dashboard</a>
      </p>
    </div>
    """
    return _send(email, f"Résumé d'appel — {caller_name or caller_phone}", html)
