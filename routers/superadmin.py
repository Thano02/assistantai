"""
Super admin dashboard — réservé aux comptes is_superadmin=True.
"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime

from database import (
    SessionLocal,
    get_business_by_id,
    get_all_active_businesses,
    update_business,
    Business,
)
from services.auth_service import get_current_business_id
from utils import get_logger

logger = get_logger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")


def require_superadmin(business_id: int = Depends(get_current_business_id)) -> int:
    db = SessionLocal()
    try:
        business = get_business_by_id(db, business_id)
        if not business or not business.is_superadmin:
            raise Exception("Forbidden")
        return business_id
    finally:
        db.close()


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
def superadmin_dashboard(request: Request, admin_id: int = Depends(require_superadmin)):
    db = SessionLocal()
    try:
        businesses = db.query(Business).filter(Business.is_superadmin == False).order_by(Business.created_at.desc()).all()
        stats = {
            "total": len(businesses),
            "paid": sum(1 for b in businesses if b.subscription_paid),
            "unpaid": sum(1 for b in businesses if not b.subscription_paid and b.is_active),
            "inactive": sum(1 for b in businesses if not b.is_active),
        }
        return templates.TemplateResponse(
            "superadmin/dashboard.html",
            {"request": request, "businesses": businesses, "stats": stats},
        )
    finally:
        db.close()


@router.get("/business/{bid}")
def superadmin_business_detail(request: Request, bid: int, admin_id: int = Depends(require_superadmin)):
    db = SessionLocal()
    try:
        business = get_business_by_id(db, bid)
        if not business:
            return RedirectResponse(url="/superadmin/dashboard")

        from database import UsageLog, Reservation, Client
        from sqlalchemy import func
        reservations_count = db.query(func.count(Reservation.id)).filter(
            Reservation.business_id == bid
        ).scalar() or 0
        clients_count = db.query(func.count(Client.id)).filter(
            Client.business_id == bid
        ).scalar() or 0

        now = datetime.utcnow()
        monthly_cost = db.query(func.sum(UsageLog.cost_eur)).filter(
            UsageLog.business_id == bid,
            func.extract("month", UsageLog.created_at) == now.month,
            func.extract("year", UsageLog.created_at) == now.year,
        ).scalar() or 0.0

        # Nombre d'appels ce mois (chaque appel = 1 entrée twilio_voice_min)
        monthly_calls = db.query(func.count(UsageLog.id)).filter(
            UsageLog.business_id == bid,
            UsageLog.event_type == "twilio_voice_min",
            func.extract("month", UsageLog.created_at) == now.month,
            func.extract("year", UsageLog.created_at) == now.year,
        ).scalar() or 0

        included_calls = 500
        overage_calls = max(0, monthly_calls - included_calls)
        overage_eur = round(overage_calls * 0.20, 2)

        return templates.TemplateResponse(
            "superadmin/business_detail.html",
            {
                "request": request,
                "business": business,
                "reservations_count": reservations_count,
                "clients_count": clients_count,
                "monthly_cost": round(monthly_cost, 4),
                "monthly_calls": monthly_calls,
                "included_calls": included_calls,
                "overage_calls": overage_calls,
                "overage_eur": overage_eur,
            },
        )
    finally:
        db.close()


@router.post("/business/{bid}/toggle")
def superadmin_toggle_business(bid: int, admin_id: int = Depends(require_superadmin)):
    db = SessionLocal()
    try:
        business = get_business_by_id(db, bid)
        if business:
            update_business(db, bid, is_active=not business.is_active)
            logger.info("Superadmin toggled business %d: is_active=%s", bid, not business.is_active)
    finally:
        db.close()
    return RedirectResponse(url=f"/superadmin/business/{bid}", status_code=303)


@router.post("/business/{bid}/payment")
def superadmin_toggle_payment(bid: int, admin_id: int = Depends(require_superadmin)):
    db = SessionLocal()
    try:
        business = get_business_by_id(db, bid)
        if business:
            new_val = not business.subscription_paid
            update_business(db, bid, subscription_paid=new_val)
            logger.info("Superadmin toggled payment for business %d: paid=%s", bid, new_val)
    finally:
        db.close()
    return RedirectResponse(url="/superadmin/dashboard", status_code=303)


@router.post("/business/{bid}/verify-email")
def superadmin_verify_email(bid: int, admin_id: int = Depends(require_superadmin)):
    db = SessionLocal()
    try:
        update_business(db, bid, email_verified=True, email_verification_token=None)
        logger.info("Superadmin force-verified email for business %d", bid)
    finally:
        db.close()
    return RedirectResponse(url=f"/superadmin/business/{bid}", status_code=303)


@router.post("/business/{bid}/plan")
def superadmin_change_plan(
    bid: int,
    plan: str = Form(...),
    admin_id: int = Depends(require_superadmin),
):
    if plan not in ("starter", "pro"):
        return RedirectResponse(url=f"/superadmin/business/{bid}", status_code=303)
    db = SessionLocal()
    try:
        update_business(db, bid, plan=plan)
        logger.info("Superadmin changed plan for business %d to %s", bid, plan)
    finally:
        db.close()
    return RedirectResponse(url=f"/superadmin/business/{bid}?success=plan_updated", status_code=303)
