"""
API d'administration.
Permet de consulter les réservations, gérer les clients, etc.
Protégé par une clé API simple (ADMIN_API_KEY dans .env).
"""
import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel
from typing import Optional
import pytz

from database import (
    SessionLocal,
    Client,
    Reservation,
    ReservationStatus,
    get_upcoming_reservations,
    get_business_by_email,
    create_business,
    update_business,
)
from config import settings, load_business_config

router = APIRouter()

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "change_me_in_env")


def verify_admin(x_api_key: str = Header(...)):
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Clé API invalide")


# ── Schemas ────────────────────────────────────────────────────────────────

class ReservationOut(BaseModel):
    id: int
    client_phone: str
    client_name: Optional[str]
    service_name: str
    appointment_dt: str
    status: str
    created_at: str

    class Config:
        from_attributes = True


class ClientOut(BaseModel):
    id: int
    phone_number: str
    name: Optional[str]
    total_reservations: int
    last_call_at: Optional[str]


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("/reservations", dependencies=[Depends(verify_admin)])
def list_reservations(
    date: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    """Liste les réservations. Filtrable par date (YYYY-MM-DD) et statut."""
    db = SessionLocal()
    try:
        tz = pytz.timezone(settings.timezone)
        query = db.query(Reservation, Client).join(Client, Reservation.client_id == Client.id)

        if date:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
            day_start = datetime.combine(target_date, datetime.min.time())
            day_end = datetime.combine(target_date, datetime.max.time())
            query = query.filter(
                Reservation.appointment_dt >= day_start,
                Reservation.appointment_dt <= day_end,
            )

        if status:
            query = query.filter(Reservation.status == status)

        query = query.order_by(Reservation.appointment_dt).limit(limit)
        results = query.all()

        out = []
        for res, client in results:
            dt = res.appointment_dt
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt).astimezone(tz)
            out.append({
                "id": res.id,
                "client_phone": client.phone_number,
                "client_name": client.name,
                "service_name": res.service_name,
                "appointment_dt": dt.strftime("%d/%m/%Y %H:%M"),
                "status": res.status,
                "created_at": res.created_at.strftime("%d/%m/%Y %H:%M"),
            })
        return {"reservations": out, "total": len(out)}
    finally:
        db.close()


@router.get("/reservations/today", dependencies=[Depends(verify_admin)])
def today_reservations():
    """Liste les réservations du jour."""
    tz = pytz.timezone(settings.timezone)
    today = datetime.now(tz).strftime("%Y-%m-%d")
    return list_reservations(date=today, status="confirmed")


@router.get("/clients", dependencies=[Depends(verify_admin)])
def list_clients(limit: int = 50):
    """Liste les clients enregistrés."""
    db = SessionLocal()
    try:
        clients = db.query(Client).order_by(Client.last_call_at.desc()).limit(limit).all()
        tz = pytz.timezone(settings.timezone)
        out = []
        for c in clients:
            last_call = None
            if c.last_call_at:
                dt = pytz.utc.localize(c.last_call_at).astimezone(tz)
                last_call = dt.strftime("%d/%m/%Y %H:%M")
            out.append({
                "id": c.id,
                "phone_number": c.phone_number,
                "name": c.name,
                "total_reservations": c.total_reservations,
                "last_call_at": last_call,
            })
        return {"clients": out, "total": len(out)}
    finally:
        db.close()


@router.delete("/reservations/{reservation_id}", dependencies=[Depends(verify_admin)])
def admin_cancel_reservation(reservation_id: int):
    """Annule une réservation depuis l'interface admin."""
    from database import cancel_reservation
    db = SessionLocal()
    try:
        res = cancel_reservation(db, reservation_id)
        if not res:
            raise HTTPException(status_code=404, detail="Réservation introuvable")
        return {"status": "cancelled", "id": reservation_id}
    finally:
        db.close()


@router.get("/business", dependencies=[Depends(verify_admin)])
def get_business_config():
    """Retourne la configuration du commerce."""
    return load_business_config()


@router.get("/stats", dependencies=[Depends(verify_admin)])
def get_stats():
    """Statistiques globales."""
    db = SessionLocal()
    try:
        total_clients = db.query(Client).count()
        total_reservations = db.query(Reservation).count()
        confirmed = db.query(Reservation).filter(
            Reservation.status == ReservationStatus.CONFIRMED
        ).count()
        cancelled = db.query(Reservation).filter(
            Reservation.status == ReservationStatus.CANCELLED
        ).count()

        tz = pytz.timezone(settings.timezone)
        today = datetime.now(tz).date()
        day_start = datetime.combine(today, datetime.min.time())
        day_end = datetime.combine(today, datetime.max.time())
        today_count = db.query(Reservation).filter(
            Reservation.appointment_dt >= day_start,
            Reservation.appointment_dt <= day_end,
            Reservation.status == ReservationStatus.CONFIRMED,
        ).count()

        return {
            "total_clients": total_clients,
            "total_reservations": total_reservations,
            "confirmed": confirmed,
            "cancelled": cancelled,
            "today_reservations": today_count,
        }
    finally:
        db.close()


@router.get("/setup-superadmin", dependencies=[Depends(verify_admin)])
def setup_superadmin(email: str, password: str, name: str = "SuperAdmin"):
    """Crée ou promeut un compte superadmin. Appeler une seule fois."""
    from services.auth_service import hash_password
    db = SessionLocal()
    try:
        existing = get_business_by_email(db, email)
        if existing:
            update_business(db, existing.id,
                            is_superadmin=True,
                            email_verified=True,
                            subscription_paid=True)
            return {"status": "ok", "message": f"{email} promu superadmin"}
        business = create_business(db, name=name, owner_email=email,
                                   password_hash=hash_password(password), plan="enterprise")
        update_business(db, business.id, is_superadmin=True,
                        email_verified=True, subscription_paid=True)
        return {"status": "ok", "message": f"Superadmin créé : {email}"}
    finally:
        db.close()
