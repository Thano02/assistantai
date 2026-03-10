"""
Webhook SMS entrant Twilio.
Permet aux clients de répondre ANNULER <id> à un SMS de rappel
pour annuler automatiquement leur réservation.
"""
import re
from fastapi import APIRouter, Form, Response
from twilio.twiml.messaging_response import MessagingResponse

from database import (
    SessionLocal,
    get_or_create_client,
    get_upcoming_reservations,
    cancel_reservation,
    Reservation,
    ReservationStatus,
)
from services.sms_service import send_cancellation_sms
from services.calendar_service import delete_calendar_event

router = APIRouter()


@router.post("/incoming")
def sms_incoming(
    Body: str = Form(""),
    From: str = Form(...),
    To: str = Form(...),
):
    """
    Traite les SMS entrants.
    Commandes supportées:
      - ANNULER <id>  → annule la réservation
      - ANNULER        → annule la prochaine réservation
      - RDV / RÉSERVER → répond avec les infos pour appeler
    """
    body = Body.strip().upper()
    caller_phone = From
    resp = MessagingResponse()

    # ── ANNULER <id> ──────────────────────────────────────────────────────
    match = re.match(r"ANNULER\s+(\d+)", body)
    if match:
        reservation_id = int(match.group(1))
        db = SessionLocal()
        try:
            res = db.query(Reservation).filter(
                Reservation.id == reservation_id,
                Reservation.status == ReservationStatus.CONFIRMED,
            ).first()

            if not res:
                resp.message("❌ Réservation introuvable ou déjà annulée.")
                return Response(content=str(resp), media_type="application/xml")

            # Vérifier que c'est bien le client concerné
            from database import Client
            client = db.query(Client).filter(Client.id == res.client_id).first()
            if client and client.phone_number != caller_phone:
                resp.message("❌ Vous n'êtes pas autorisé à annuler cette réservation.")
                return Response(content=str(resp), media_type="application/xml")

            service = res.service_name
            appointment_dt = res.appointment_dt
            google_event_id = res.google_event_id

            cancel_reservation(db, reservation_id)

            if google_event_id:
                delete_calendar_event(google_event_id)

            from services.sms_service import format_dt_fr
            dt_str = format_dt_fr(appointment_dt)
            resp.message(
                f"✅ Votre RDV du {dt_str} ({service}) a bien été annulé.\n"
                f"Pour reprendre RDV, appelez-nous !"
            )
        finally:
            db.close()
        return Response(content=str(resp), media_type="application/xml")

    # ── ANNULER sans id → annuler la prochaine ────────────────────────────
    if body == "ANNULER":
        db = SessionLocal()
        try:
            reservations = get_upcoming_reservations(db, caller_phone)
            if not reservations:
                resp.message("❌ Vous n'avez aucun RDV à venir à annuler.")
            else:
                r = reservations[0]
                from services.sms_service import format_dt_fr
                dt_str = format_dt_fr(r.appointment_dt)
                google_event_id = r.google_event_id
                cancel_reservation(db, r.id)
                if google_event_id:
                    delete_calendar_event(google_event_id)
                resp.message(
                    f"✅ Votre RDV du {dt_str} ({r.service_name}) a bien été annulé.\n"
                    f"Pour reprendre RDV, appelez-nous !"
                )
        finally:
            db.close()
        return Response(content=str(resp), media_type="application/xml")

    # ── MES RDV → liste les prochains RDV ────────────────────────────────
    if body in ("MES RDV", "MES RENDEZ-VOUS", "RDV"):
        db = SessionLocal()
        try:
            reservations = get_upcoming_reservations(db, caller_phone)
            if not reservations:
                resp.message("Vous n'avez aucun RDV à venir. Appelez-nous pour réserver !")
            else:
                from services.sms_service import format_dt_fr
                lines = ["📅 Vos prochains RDV :"]
                for r in reservations[:3]:
                    dt_str = format_dt_fr(r.appointment_dt)
                    lines.append(f"• {r.service_name} — {dt_str} (#{r.id})")
                lines.append("\nPour annuler: répondez ANNULER <numéro>")
                resp.message("\n".join(lines))
        finally:
            db.close()
        return Response(content=str(resp), media_type="application/xml")

    # ── Message non reconnu ───────────────────────────────────────────────
    resp.message(
        "Commandes disponibles :\n"
        "• ANNULER <numéro> — annuler un RDV\n"
        "• MES RDV — voir vos prochains RDV\n\n"
        "Pour prendre RDV, appelez-nous !"
    )
    return Response(content=str(resp), media_type="application/xml")
