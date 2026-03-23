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
    base = settings.base_url.rstrip("/")
    verify_url = f"{base}/auth/verify-email/{token}"
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
        Ce lien expire dans 2 heures. Si vous n'avez pas créé de compte, ignorez cet e-mail.
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


# ── Notification nouveau paiement (owner) ─────────────────────────────────────

def send_new_payment_notification(business_name: str, business_email: str, business_id: int) -> bool:
    admin_url = f"{settings.base_url.rstrip('/')}/superadmin/business/{business_id}"
    html = f"""
    <div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;padding:40px 20px">
      <h2 style="color:#1a1a2e;margin-bottom:8px">💰 Nouveau client payant !</h2>
      <p style="color:#6b7280;margin-bottom:24px">
        Un client vient de régler son essai et est maintenant actif sur AssistantAI.
      </p>
      <table style="width:100%;border-collapse:collapse;font-size:14px;color:#374151;margin-bottom:24px">
        <tr><td style="padding:8px 0;font-weight:600;width:140px">Commerce :</td><td><strong>{business_name}</strong></td></tr>
        <tr><td style="padding:8px 0;font-weight:600">Email :</td><td><a href="mailto:{business_email}" style="color:#2563eb">{business_email}</a></td></tr>
      </table>
      <div style="background:#fef3c7;border:1px solid #f59e0b;border-radius:10px;padding:16px;margin-bottom:24px">
        <p style="margin:0;font-weight:600;color:#92400e">⚠️ Action requise</p>
        <p style="margin:6px 0 0;color:#92400e;font-size:14px">
          Achetez et configurez un numéro Twilio pour ce client, puis envoyez-le lui depuis le superadmin.
        </p>
      </div>
      <a href="{admin_url}"
         style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;
                padding:14px 28px;border-radius:10px;font-weight:600;font-size:15px">
        Voir le client dans le superadmin →
      </a>
    </div>
    """
    return _send("ethan36@hotmail.fr", f"💰 Nouveau client : {business_name}", html)


def send_phone_number_to_client(business_email: str, business_name: str, phone_number: str) -> bool:
    html = f"""
    <div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;padding:40px 20px">
      <h2 style="color:#1a1a2e;margin-bottom:8px">Votre ligne téléphonique est prête ! 🎉</h2>
      <p style="color:#6b7280;margin-bottom:24px">
        Bonjour <strong>{business_name}</strong>,<br><br>
        Votre assistant vocal est maintenant opérationnel. Voici votre numéro de téléphone dédié :
      </p>
      <div style="background:#eff6ff;border:2px solid #2563eb;border-radius:12px;padding:20px;text-align:center;margin-bottom:24px">
        <p style="margin:0;font-size:28px;font-weight:800;color:#1d4ed8;letter-spacing:2px">{phone_number}</p>
        <p style="margin:8px 0 0;color:#6b7280;font-size:13px">Votre numéro AssistantAI</p>
      </div>
      <p style="color:#374151;font-size:14px;margin-bottom:16px">
        <strong>Comment tester :</strong><br>
        Appelez ce numéro depuis votre téléphone — votre assistant vocal répondra et pourra prendre des rendez-vous pour vous.
      </p>
      <p style="color:#374151;font-size:14px;margin-bottom:24px">
        Pensez à configurer vos <strong>horaires</strong> et vos <strong>services</strong> depuis votre espace client pour que le robot soit parfaitement paramétré.
      </p>
      <a href="{settings.base_url.rstrip('/')}/dashboard"
         style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;
                padding:14px 28px;border-radius:10px;font-weight:600;font-size:15px">
        Accéder à mon espace client →
      </a>
      <p style="color:#9ca3af;font-size:12px;margin-top:32px">
        Une question ? Répondez à cet email ou contactez-nous à contact@assistantai.fr
      </p>
    </div>
    """
    return _send(business_email, f"Votre numéro AssistantAI est prêt — {phone_number}", html)


# ── Password reset ────────────────────────────────────────────────────────────

def send_password_reset_email(email: str, token: str) -> bool:
    base = settings.base_url.rstrip("/")
    reset_url = f"{base}/auth/reset-password/{token}"
    html = f"""
    <div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;padding:40px 20px">
      <h2 style="color:#1a1a2e;margin-bottom:8px">Réinitialisation du mot de passe</h2>
      <p style="color:#6b7280;margin-bottom:24px">
        Vous avez demandé à réinitialiser votre mot de passe. Cliquez sur le bouton ci-dessous.
        Ce lien est valable <strong>2 heures</strong>.
      </p>
      <a href="{reset_url}"
         style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;
                padding:14px 28px;border-radius:10px;font-weight:600;font-size:15px">
        Réinitialiser mon mot de passe
      </a>
      <p style="color:#9ca3af;font-size:12px;margin-top:32px">
        Si vous n'avez pas fait cette demande, ignorez cet e-mail. Votre mot de passe ne sera pas modifié.
      </p>
    </div>
    """
    return _send(email, "Réinitialisation de votre mot de passe — AssistantAI", html)


# ── Call summary ──────────────────────────────────────────────────────────────

def send_contact_request_email(
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
    project_description: str,
) -> bool:
    html = f"""
    <div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;padding:40px 20px">
      <h2 style="color:#1a1a2e;margin-bottom:4px">Nouvelle demande de contact</h2>
      <p style="color:#9ca3af;font-size:13px;margin-bottom:24px">Reçue depuis la page Fonctionnalités</p>
      <table style="width:100%;border-collapse:collapse;font-size:14px;color:#374151">
        <tr><td style="padding:8px 0;font-weight:600;width:140px">Prénom&nbsp;:</td><td>{first_name}</td></tr>
        <tr><td style="padding:8px 0;font-weight:600">Nom&nbsp;:</td><td>{last_name}</td></tr>
        <tr><td style="padding:8px 0;font-weight:600">Email&nbsp;:</td><td><a href="mailto:{email}" style="color:#2563eb">{email}</a></td></tr>
        <tr><td style="padding:8px 0;font-weight:600">Téléphone&nbsp;:</td><td>{phone or '—'}</td></tr>
      </table>
      <div style="margin-top:20px;background:#f3f4f6;border-radius:10px;padding:16px">
        <p style="margin:0;font-weight:600;color:#374151;margin-bottom:8px">Projet / Message&nbsp;:</p>
        <p style="margin:0;color:#374151;font-size:14px;white-space:pre-line">{project_description}</p>
      </div>
      <p style="color:#9ca3af;font-size:12px;margin-top:32px">— AssistantAI</p>
    </div>
    """
    return _send("ethan36@hotmail.fr", f"Nouvelle demande — {first_name} {last_name}", html)


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
