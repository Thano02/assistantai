"""
API REST pour le calendrier du dashboard.
Retourne et gère les événements au format FullCalendar.
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import pytz

from config import settings
from database import (
    SessionLocal,
    Reservation,
    Client,
    ReservationStatus,
    get_business_by_id,
    create_reservation,
    cancel_reservation,
    modify_reservation,
    get_or_create_client,
)
from services.auth_service import get_current_business_id
from services.sms_service import send_confirmation_sms, send_cancellation_sms
from services.slots_service import get_service_duration

router = APIRouter()

# Couleurs par type de source
COLOR_ROBOT = "#2563eb"       # Bleu — RDV pris par le robot
COLOR_MANUAL = "#7c3aed"      # Violet — RDV ajouté manuellement
COLOR_GOOGLE = "#16a34a"      # Vert — Google Calendar
COLOR_OUTLOOK = "#ea580c"     # Orange — Outlook


def _reservation_to_event(res: Reservation, client: Client) -> dict:
    tz = pytz.timezone(settings.timezone)
    start = res.appointment_dt
    if start.tzinfo is None:
        start = pytz.utc.localize(start).astimezone(tz)
    end = start + timedelta(minutes=res.duration_minutes)

    return {
        "id": res.id,
        "title": f"{res.service_name} — {client.name or client.phone_number}",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "color": COLOR_ROBOT,
        "extendedProps": {
            "source": "robot",
            "client_name": client.name or "",
            "client_phone": client.phone_number,
            "service": res.service_name,
            "duration": res.duration_minutes,
            "status": res.status,
            "reservation_id": res.id,
        },
    }


# ── GET /api/calendar/events ──────────────────────────────────────────────────

@router.get("/events")
def get_events(
    start: str = Query(...),
    end: str = Query(...),
    business_id: int = Depends(get_current_business_id),
):
    """
    Retourne les événements pour la plage [start, end].
    Inclut : réservations DB + Google Calendar + Outlook.
    """
    db = SessionLocal()
    events = []
    try:
        # Convertir les dates
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except ValueError:
            start_dt = datetime.strptime(start[:10], "%Y-%m-%d")
            end_dt = datetime.strptime(end[:10], "%Y-%m-%d")

        # ── Réservations DB ────────────────────────────────────────────────
        reservations = (
            db.query(Reservation, Client)
            .join(Client, Reservation.client_id == Client.id)
            .filter(
                Reservation.business_id == business_id,
                Reservation.appointment_dt >= start_dt,
                Reservation.appointment_dt <= end_dt,
                Reservation.status == ReservationStatus.CONFIRMED,
            )
            .all()
        )
        for res, client in reservations:
            events.append(_reservation_to_event(res, client))

        # ── Google Calendar ────────────────────────────────────────────────
        business = get_business_by_id(db, business_id)
        if business and business.google_access_token and business.google_calendar_id:
            try:
                from services.calendar_service import get_calendar_busy_slots
                # Utiliser les tokens du business spécifique
                google_events = _get_google_events(
                    business.google_access_token,
                    business.google_calendar_id,
                    start_dt,
                    end_dt,
                )
                events.extend(google_events)
            except Exception as e:
                print(f"[Calendar API] Google Calendar error: {e}")

        # ── Outlook ────────────────────────────────────────────────────────
        if business and business.outlook_access_token and business.outlook_calendar_id:
            try:
                from services.outlook_service import get_events as outlook_get_events
                raw = outlook_get_events(
                    business.outlook_access_token,
                    business.outlook_calendar_id,
                    start_dt,
                    end_dt,
                )
                for ev in raw:
                    events.append({
                        "id": f"outlook_{ev['id'][:20]}",
                        "title": ev.get("subject", "(sans titre)"),
                        "start": ev["start"]["dateTime"],
                        "end": ev["end"]["dateTime"],
                        "color": COLOR_OUTLOOK,
                        "extendedProps": {"source": "outlook"},
                    })
            except Exception as e:
                print(f"[Calendar API] Outlook error: {e}")

    finally:
        db.close()

    return events


def _get_google_events(access_token: str, calendar_id: str, start_dt: datetime, end_dt: datetime) -> list:
    """Récupère les événements Google Calendar via l'API REST."""
    import httpx
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "timeMin": start_dt.isoformat() + ("Z" if not start_dt.utcoffset() else ""),
        "timeMax": end_dt.isoformat() + ("Z" if not end_dt.utcoffset() else ""),
        "singleEvents": "true",
        "maxResults": 100,
    }
    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    with httpx.Client(timeout=10) as client:
        r = client.get(url, headers=headers, params=params)
        r.raise_for_status()
        items = r.json().get("items", [])

    events = []
    for item in items:
        start = item.get("start", {})
        end = item.get("end", {})
        events.append({
            "id": f"google_{item['id'][:20]}",
            "title": item.get("summary", "(sans titre)"),
            "start": start.get("dateTime") or start.get("date"),
            "end": end.get("dateTime") or end.get("date"),
            "color": COLOR_GOOGLE,
            "extendedProps": {"source": "google"},
        })
    return events


# ── POST /api/calendar/events — Créer un RDV manuellement ────────────────────

class CreateEventBody(BaseModel):
    client_name: str
    client_phone: str
    service_name: str
    start: str            # ISO 8601
    duration_minutes: int = 30
    send_sms: bool = True


@router.post("/events")
def create_event(
    body: CreateEventBody,
    business_id: int = Depends(get_current_business_id),
):
    tz = pytz.timezone(settings.timezone)
    try:
        start_dt = datetime.fromisoformat(body.start)
        if start_dt.tzinfo is None:
            start_dt = tz.localize(start_dt)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format de date invalide")

    duration = body.duration_minutes or get_service_duration(body.service_name) or 30

    db = SessionLocal()
    try:
        client = get_or_create_client(db, body.client_phone)
        if body.client_name and not client.name:
            client.name = body.client_name
            db.commit()

        res = create_reservation(
            db,
            body.client_phone,
            body.service_name,
            start_dt,
            duration,
        )
        res.business_id = business_id
        db.commit()

        if body.send_sms and body.client_phone:
            send_confirmation_sms(
                body.client_phone,
                body.client_name,
                body.service_name,
                start_dt,
                res.id,
            )

        return {"success": True, "id": res.id}
    finally:
        db.close()


# ── PUT /api/calendar/events/{id} — Modifier un RDV ─────────────────────────

class UpdateEventBody(BaseModel):
    start: str
    duration_minutes: Optional[int] = None


@router.put("/events/{reservation_id}")
def update_event(
    reservation_id: int,
    body: UpdateEventBody,
    business_id: int = Depends(get_current_business_id),
):
    tz = pytz.timezone(settings.timezone)
    try:
        new_dt = datetime.fromisoformat(body.start)
        if new_dt.tzinfo is None:
            new_dt = tz.localize(new_dt)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format de date invalide")

    db = SessionLocal()
    try:
        res = db.query(Reservation).filter(
            Reservation.id == reservation_id,
            Reservation.business_id == business_id,
        ).first()
        if not res:
            raise HTTPException(status_code=404, detail="Réservation introuvable")

        modify_reservation(db, reservation_id, new_dt)

        if body.duration_minutes:
            res.duration_minutes = body.duration_minutes
            db.commit()

        # Mise à jour calendrier externe
        if res.google_event_id:
            business = get_business_by_id(db, business_id)
            if business and business.google_access_token:
                from services.calendar_service import update_calendar_event
                update_calendar_event(res.google_event_id, new_dt, res.duration_minutes)

        return {"success": True}
    finally:
        db.close()


# ── DELETE /api/calendar/events/{id} — Annuler un RDV ───────────────────────

@router.delete("/events/{reservation_id}")
def delete_event(
    reservation_id: int,
    business_id: int = Depends(get_current_business_id),
):
    db = SessionLocal()
    try:
        res = db.query(Reservation).filter(
            Reservation.id == reservation_id,
            Reservation.business_id == business_id,
        ).first()
        if not res:
            raise HTTPException(status_code=404, detail="Réservation introuvable")

        client = db.query(Client).filter(Client.id == res.client_id).first()
        service = res.service_name
        appointment_dt = res.appointment_dt
        google_event_id = res.google_event_id

        cancel_reservation(db, reservation_id)

        if google_event_id:
            business = get_business_by_id(db, business_id)
            if business and business.google_access_token:
                from services.calendar_service import delete_calendar_event
                delete_calendar_event(google_event_id)

        if client:
            send_cancellation_sms(client.phone_number, service, appointment_dt)

        return {"success": True}
    finally:
        db.close()


# ── GET /api/calendar/available-slots ────────────────────────────────────────

@router.get("/available-slots")
def available_slots(
    date: str = Query(...),
    service: str = Query(...),
    business_id: int = Depends(get_current_business_id),
):
    from database import get_taken_slots
    from services.slots_service import get_available_slots, get_service_duration, parse_date_fr

    date_str = parse_date_fr(date) or date
    duration = get_service_duration(service) or 30
    db = SessionLocal()
    try:
        taken = get_taken_slots(db, date_str)
        slots = get_available_slots(taken, date_str, duration, max_slots=10)
        return {
            "date": date_str,
            "service": service,
            "duration_minutes": duration,
            "slots": [s.isoformat() for s in slots],
        }
    finally:
        db.close()
