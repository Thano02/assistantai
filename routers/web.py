"""
Routes HTML — pages web du dashboard SaaS.
"""
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Query, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
import pytz

from config import settings
from database import (
    SessionLocal,
    Reservation,
    Client,
    ReservationStatus,
    ContactRequest,
    get_business_by_id,
    get_monthly_usage,
)
from services.auth_service import get_current_business_id, get_current_business_id_optional
from services.stripe_service import get_invoice_list, get_customer_portal_url

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _check_subscription(business):
    """Redirect clients with unpaid subscription to /suspended."""
    if business and not business.is_superadmin and not business.subscription_paid:
        return RedirectResponse(url="/suspended", status_code=303)
    return None


# ── Landing page ──────────────────────────────────────────────────────────────

@router.get("/suspended")
def suspended_page(request: Request):
    return templates.TemplateResponse("suspended.html", {"request": request})


@router.get("/")
def landing(request: Request):
    business_id = get_current_business_id_optional(request)
    if business_id:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("landing.html", {"request": request})


@router.get("/features")
def features_page(request: Request, contact_success: str = Query(None)):
    return templates.TemplateResponse("features.html", {
        "request": request,
        "contact_success": contact_success == "1",
    })


@router.post("/features/contact")
def features_contact(
    request: Request,
    first_name: str = Form(None),
    last_name: str = Form(None),
    email: str = Form(None),
    phone: str = Form(None),
    project_description: str = Form(None),
):
    db = SessionLocal()
    try:
        if first_name and last_name and email and project_description:
            db.add(ContactRequest(
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone or "",
                project_description=project_description,
            ))
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/features?contact_success=1#contact", status_code=303)


@router.get("/pricing")
def pricing(request: Request):
    return templates.TemplateResponse("pricing.html", {
        "request": request,
        "stripe_publishable_key": settings.stripe_publishable_key,
    })


# ── Dashboard principal ───────────────────────────────────────────────────────

@router.get("/dashboard")
def dashboard(
    request: Request,
    business_id: int = Depends(get_current_business_id),
):
    db = SessionLocal()
    try:
        business = get_business_by_id(db, business_id)
        if not business:
            return RedirectResponse(url="/login")

        # Superadmin → redirect to superadmin dashboard
        if business.is_superadmin:
            return RedirectResponse(url="/superadmin/dashboard", status_code=302)

        # Unpaid subscription → suspended page
        gate = _check_subscription(business)
        if gate:
            return gate

        tz = pytz.timezone(settings.timezone)
        today = datetime.now(tz).date()
        day_start = datetime.combine(today, datetime.min.time())
        day_end = datetime.combine(today, datetime.max.time())

        # Stats du jour
        today_reservations = (
            db.query(Reservation, Client)
            .join(Client, Reservation.client_id == Client.id)
            .filter(
                Reservation.business_id == business_id,
                Reservation.appointment_dt >= day_start,
                Reservation.appointment_dt <= day_end,
                Reservation.status == ReservationStatus.CONFIRMED,
            )
            .order_by(Reservation.appointment_dt)
            .all()
        )

        # Stats générales
        total_clients = db.query(Client).filter(Client.business_id == business_id).count()
        total_confirmed = db.query(Reservation).filter(
            Reservation.business_id == business_id,
            Reservation.status == ReservationStatus.CONFIRMED,
        ).count()
        total_cancelled = db.query(Reservation).filter(
            Reservation.business_id == business_id,
            Reservation.status == ReservationStatus.CANCELLED,
        ).count()

        # Prochains RDV (7 jours)
        from datetime import timedelta
        upcoming = (
            db.query(Reservation, Client)
            .join(Client, Reservation.client_id == Client.id)
            .filter(
                Reservation.business_id == business_id,
                Reservation.appointment_dt >= datetime.now(tz),
                Reservation.appointment_dt <= datetime.now(tz) + timedelta(days=7),
                Reservation.status == ReservationStatus.CONFIRMED,
            )
            .order_by(Reservation.appointment_dt)
            .limit(10)
            .all()
        )

        # Usage du mois courant
        now = datetime.now(tz)
        usage = get_monthly_usage(db, business_id, now.year, now.month)

        def fmt_dt(dt):
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt).astimezone(tz)
            else:
                dt = dt.astimezone(tz)
            return dt.strftime("%d/%m à %Hh%M")

        today_list = [
            {
                "id": r.id,
                "service": r.service_name,
                "client": c.name or c.phone_number,
                "time": fmt_dt(r.appointment_dt),
                "duration": r.duration_minutes,
            }
            for r, c in today_reservations
        ]
        upcoming_list = [
            {
                "id": r.id,
                "service": r.service_name,
                "client": c.name or c.phone_number,
                "datetime": fmt_dt(r.appointment_dt),
                "duration": r.duration_minutes,
            }
            for r, c in upcoming
        ]

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "business": business,
            "today_reservations": today_list,
            "today_count": len(today_list),
            "total_clients": total_clients,
            "total_confirmed": total_confirmed,
            "total_cancelled": total_cancelled,
            "upcoming": upcoming_list,
            "usage": usage,
            "page": "dashboard",
        })
    finally:
        db.close()


# ── Calendrier ────────────────────────────────────────────────────────────────

@router.get("/dashboard/calendar")
def calendar_view(
    request: Request,
    business_id: int = Depends(get_current_business_id),
):
    db = SessionLocal()
    try:
        business = get_business_by_id(db, business_id)
        gate = _check_subscription(business)
        if gate:
            return gate
        from config import load_business_config
        business_cfg = load_business_config()
        return templates.TemplateResponse("calendar_view.html", {
            "request": request,
            "business": business,
            "services": business_cfg.get("services", []),
            "page": "calendar",
        })
    finally:
        db.close()


# ── Paramètres ────────────────────────────────────────────────────────────────

@router.get("/dashboard/settings")
def settings_page(
    request: Request,
    success: str = Query(None),
    error: str = Query(None),
    business_id: int = Depends(get_current_business_id),
):
    db = SessionLocal()
    try:
        business = get_business_by_id(db, business_id)
        # Superadmin → page complète ; client → page simplifiée voix uniquement
        if business and business.is_superadmin:
            from config import load_business_config
            business_cfg = load_business_config()
            return templates.TemplateResponse("settings.html", {
                "request": request,
                "business": business,
                "business_cfg": business_cfg,
                "success": success,
                "error": error,
                "google_connected": bool(business.google_access_token),
                "outlook_connected": bool(business.outlook_access_token),
                "base_url": settings.base_url,
                "google_enabled": bool(settings.google_client_id),
                "outlook_enabled": settings.outlook_enabled,
                "page": "settings",
            })
        return RedirectResponse(url="/dashboard/client-settings", status_code=302)
    finally:
        db.close()


@router.get("/dashboard/client-settings")
def client_settings_page(
    request: Request,
    success: str = Query(None),
    business_id: int = Depends(get_current_business_id),
):
    db = SessionLocal()
    try:
        business = get_business_by_id(db, business_id)
        gate = _check_subscription(business)
        if gate:
            return gate
        guillaume_id = settings.elevenlabs_voice_id
        preset_voices = [
            ("Guillaume", guillaume_id, "Naturel, professionnel — homme"),
            ("Audrey", "McVZB9hVxVSk3Equu8EH", "Douce, chaleureuse — femme"),
            ("Koraly", "MNKK2Wl2wbbsEPQTHZGt", "Claire, expressive — femme"),
            ("Anthony", "1EmYoP3UnnnwhlJKovEy", "Grave, rassurant — homme"),
        ]
        preset_voice_ids = [v[1] for v in preset_voices]
        return templates.TemplateResponse("dashboard/client_settings.html", {
            "request": request,
            "business": business,
            "success": success,
            "preset_voices": preset_voices,
            "preset_voice_ids": preset_voice_ids,
            "page": "settings",
        })
    finally:
        db.close()


@router.post("/dashboard/client-settings")
def client_settings_save(
    request: Request,
    business_name: str = Form(None),
    owner_phone: str = Form(None),
    voice_preset: str = Form(None),
    voice_id: str = Form(None),
    business_id: int = Depends(get_current_business_id),
):
    from database import update_business
    db = SessionLocal()
    try:
        updates = {}
        if business_name:
            updates["name"] = business_name
        if owner_phone is not None:
            updates["owner_phone"] = owner_phone.strip() or None
        # Preset a priority, then custom
        chosen_voice = voice_preset or voice_id or None
        if chosen_voice:
            updates["elevenlabs_voice_id"] = chosen_voice
        if updates:
            update_business(db, business_id, **updates)
        return RedirectResponse(url="/dashboard/client-settings?success=saved", status_code=303)
    finally:
        db.close()


@router.post("/dashboard/settings")
def settings_save(
    request: Request,
    business_name: str = None,
    twilio_phone: str = None,
    twilio_sid: str = None,
    twilio_token: str = None,
    voice_id: str = None,
    business_id: int = Depends(get_current_business_id),
):
    from database import update_business
    db = SessionLocal()
    try:
        updates = {}
        if business_name:
            updates["name"] = business_name
        if twilio_phone:
            updates["twilio_phone_number"] = twilio_phone
        if twilio_sid:
            updates["twilio_account_sid"] = twilio_sid
        if twilio_token:
            updates["twilio_auth_token"] = twilio_token
        if voice_id:
            updates["elevenlabs_voice_id"] = voice_id
        if updates:
            update_business(db, business_id, **updates)
        return RedirectResponse(url="/dashboard/settings?success=saved", status_code=303)
    finally:
        db.close()


# ── FAQ ───────────────────────────────────────────────────────────────────────

@router.get("/dashboard/faq")
def faq_page(
    request: Request,
    success: str = Query(None),
    business_id: int = Depends(get_current_business_id),
):
    db = SessionLocal()
    try:
        business = get_business_by_id(db, business_id)
        if not business:
            return RedirectResponse(url="/auth/login")
        gate = _check_subscription(business)
        if gate:
            return gate
        from database import get_faqs
        faqs = get_faqs(db, business_id)
        return templates.TemplateResponse("dashboard/faq.html", {
            "request": request,
            "business": business,
            "faqs": faqs,
            "success": success,
            "page": "faq",
        })
    finally:
        db.close()


@router.post("/dashboard/faq")
def faq_add(
    request: Request,
    question: str = None,
    answer: str = None,
    business_id: int = Depends(get_current_business_id),
):
    from database import create_faq, get_faqs
    if not question or not answer:
        return RedirectResponse(url="/dashboard/faq", status_code=303)
    db = SessionLocal()
    try:
        faqs = get_faqs(db, business_id)
        create_faq(db, business_id, question, answer, order_index=len(faqs))
        return RedirectResponse(url="/dashboard/faq?success=saved", status_code=303)
    finally:
        db.close()


@router.post("/dashboard/faq/{faq_id}/update")
def faq_update(
    faq_id: int,
    question: str = None,
    answer: str = None,
    business_id: int = Depends(get_current_business_id),
):
    from database import update_faq
    if not question or not answer:
        return RedirectResponse(url="/dashboard/faq", status_code=303)
    db = SessionLocal()
    try:
        update_faq(db, faq_id, business_id, question=question, answer=answer)
        return RedirectResponse(url="/dashboard/faq?success=saved", status_code=303)
    finally:
        db.close()


@router.post("/dashboard/faq/{faq_id}/delete")
def faq_delete(
    faq_id: int,
    business_id: int = Depends(get_current_business_id),
):
    from database import delete_faq
    db = SessionLocal()
    try:
        delete_faq(db, faq_id, business_id)
        return RedirectResponse(url="/dashboard/faq?success=deleted", status_code=303)
    finally:
        db.close()


@router.post("/dashboard/faq/profession")
def faq_set_profession(
    profession_type: str = None,
    business_id: int = Depends(get_current_business_id),
):
    from database import update_business
    db = SessionLocal()
    try:
        if profession_type:
            update_business(db, business_id, profession_type=profession_type)
        return RedirectResponse(url="/dashboard/faq?success=saved", status_code=303)
    finally:
        db.close()


@router.post("/dashboard/faq/load-defaults")
def faq_load_defaults(business_id: int = Depends(get_current_business_id)):
    from database import get_business_by_id, FAQ
    from services.faq_service import get_default_faq
    from database import bulk_create_faqs
    db = SessionLocal()
    try:
        business = get_business_by_id(db, business_id)
        if not business:
            return RedirectResponse(url="/dashboard/faq")
        # Delete existing FAQs for this business
        db.query(FAQ).filter(FAQ.business_id == business_id).delete()
        db.commit()
        items = get_default_faq(business.profession_type or "autre")
        bulk_create_faqs(db, business_id, items)
        return RedirectResponse(url="/dashboard/faq?success=defaults_loaded", status_code=303)
    finally:
        db.close()


# ── Facturation ───────────────────────────────────────────────────────────────

@router.get("/dashboard/billing")
def billing_page(
    request: Request,
    success: str = Query(None),
    business_id: int = Depends(get_current_business_id),
):
    db = SessionLocal()
    try:
        business = get_business_by_id(db, business_id)
        gate = _check_subscription(business)
        if gate:
            return gate
        tz = pytz.timezone(settings.timezone)
        now = datetime.now(tz)

        # Usage du mois courant
        usage = get_monthly_usage(db, business_id, now.year, now.month)

        # Factures Stripe
        stripe_invoices = []
        if business.stripe_customer_id:
            stripe_invoices = get_invoice_list(business.stripe_customer_id)

        # Factures internes
        from database import MonthlyInvoice
        db_invoices = (
            db.query(MonthlyInvoice)
            .filter(MonthlyInvoice.business_id == business_id)
            .order_by(MonthlyInvoice.period_start.desc())
            .limit(12)
            .all()
        )

        plan_price = settings.plan_prices.get(business.plan, 29.0)

        return templates.TemplateResponse("billing.html", {
            "request": request,
            "business": business,
            "usage": usage,
            "plan_price": plan_price,
            "estimated_total": plan_price + usage.get("billed_eur", 0),
            "stripe_invoices": stripe_invoices,
            "db_invoices": db_invoices,
            "success": success,
            "portal_available": bool(business.stripe_customer_id and settings.stripe_enabled),
            "page": "billing",
        })
    finally:
        db.close()
