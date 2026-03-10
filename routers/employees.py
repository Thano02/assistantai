"""
API et pages pour la gestion des employés (multi-tenant).
"""
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from database import (
    SessionLocal,
    get_employees,
    get_employee_by_id,
    create_employee,
    update_employee,
    deactivate_employee,
    save_oauth_state,
    pop_oauth_state,
    update_business,
)
from services.auth_service import get_current_business_id
from utils import get_logger

logger = get_logger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")


# ── Page employés ─────────────────────────────────────────────────────────────

@router.get("/dashboard/employees")
def employees_page(request: Request, business_id: int = Depends(get_current_business_id)):
    db = SessionLocal()
    try:
        from database import get_business_by_id
        business = get_business_by_id(db, business_id)
        employees = get_employees(db, business_id)
        return templates.TemplateResponse(
            "dashboard/employees.html",
            {"request": request, "business": business, "employees": employees,
             "success": request.query_params.get("success"),
             "error": request.query_params.get("error")},
        )
    finally:
        db.close()


# ── CRUD API ──────────────────────────────────────────────────────────────────

@router.post("/api/employees")
def create_employee_api(
    request: Request,
    name: str = Form(...),
    specialty: str = Form(None),
    business_id: int = Depends(get_current_business_id),
):
    db = SessionLocal()
    try:
        employee = create_employee(db, business_id, name, specialty)
        return RedirectResponse(url="/dashboard/employees?success=created", status_code=303)
    finally:
        db.close()


@router.post("/api/employees/{employee_id}/update")
def update_employee_api(
    employee_id: int,
    name: str = Form(...),
    specialty: str = Form(None),
    business_id: int = Depends(get_current_business_id),
):
    db = SessionLocal()
    try:
        update_employee(db, employee_id, business_id, name=name, specialty=specialty)
        return RedirectResponse(url="/dashboard/employees?success=updated", status_code=303)
    finally:
        db.close()


@router.post("/api/employees/{employee_id}/delete")
def delete_employee_api(
    employee_id: int,
    business_id: int = Depends(get_current_business_id),
):
    db = SessionLocal()
    try:
        deactivate_employee(db, employee_id, business_id)
        return RedirectResponse(url="/dashboard/employees?success=deleted", status_code=303)
    finally:
        db.close()


@router.post("/api/employees/toggle-selection")
def toggle_employee_selection(business_id: int = Depends(get_current_business_id)):
    db = SessionLocal()
    try:
        from database import get_business_by_id
        business = get_business_by_id(db, business_id)
        if business:
            update_business(db, business_id, employee_selection_enabled=not business.employee_selection_enabled)
    finally:
        db.close()
    return RedirectResponse(url="/dashboard/employees", status_code=303)


# ── OAuth Google par employé ──────────────────────────────────────────────────

@router.get("/auth/employee/{employee_id}/google")
def employee_google_connect(
    employee_id: int,
    business_id: int = Depends(get_current_business_id),
):
    from config import settings
    db = SessionLocal()
    try:
        emp = get_employee_by_id(db, employee_id, business_id)
        if not emp:
            return RedirectResponse(url="/dashboard/employees?error=not_found")
        state = secrets.token_urlsafe(16)
        save_oauth_state(db, state, business_id, employee_id=employee_id)
    finally:
        db.close()

    redirect_uri = f"{settings.base_url}/auth/employee/google-callback"
    scope = "https://www.googleapis.com/auth/calendar"
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={settings.google_client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&state={state}"
    )
    return RedirectResponse(url=auth_url)


@router.get("/auth/employee/google-callback")
def employee_google_callback(code: str = None, state: str = None, error: str = None):
    if error or not code or not state:
        return RedirectResponse(url="/dashboard/employees?error=google_cancelled")

    db = SessionLocal()
    try:
        state_obj = pop_oauth_state(db, state)
        if not state_obj or not state_obj.employee_id:
            return RedirectResponse(url="/dashboard/employees?error=invalid_state")
        employee_id = state_obj.employee_id
        business_id = state_obj.business_id
    finally:
        db.close()

    from config import settings
    import httpx

    try:
        with httpx.Client() as client:
            r = client.post("https://oauth2.googleapis.com/token", data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": f"{settings.base_url}/auth/employee/google-callback",
                "grant_type": "authorization_code",
            })
            r.raise_for_status()
            tokens = r.json()

        expiry = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))
        db = SessionLocal()
        try:
            update_employee(
                db, employee_id, business_id,
                google_access_token=tokens["access_token"],
                google_refresh_token=tokens.get("refresh_token"),
                google_token_expiry=expiry,
            )
        finally:
            db.close()
        return RedirectResponse(url="/dashboard/employees?success=google_connected")
    except Exception as e:
        logger.error("Employee Google OAuth error: %s", e)
        return RedirectResponse(url="/dashboard/employees?error=google_failed")


# ── OAuth Outlook par employé ─────────────────────────────────────────────────

@router.get("/auth/employee/{employee_id}/outlook")
def employee_outlook_connect(
    employee_id: int,
    business_id: int = Depends(get_current_business_id),
):
    from services.outlook_service import get_auth_url as outlook_auth_url
    db = SessionLocal()
    try:
        emp = get_employee_by_id(db, employee_id, business_id)
        if not emp:
            return RedirectResponse(url="/dashboard/employees?error=not_found")
        state = secrets.token_urlsafe(16)
        save_oauth_state(db, state, business_id, employee_id=employee_id)
    finally:
        db.close()
    return RedirectResponse(url=outlook_auth_url(state))


@router.get("/auth/employee/outlook-callback")
def employee_outlook_callback(code: str = None, state: str = None, error: str = None):
    if error or not code or not state:
        return RedirectResponse(url="/dashboard/employees?error=outlook_cancelled")

    db = SessionLocal()
    try:
        state_obj = pop_oauth_state(db, state)
        if not state_obj or not state_obj.employee_id:
            return RedirectResponse(url="/dashboard/employees?error=invalid_state")
        employee_id = state_obj.employee_id
        business_id = state_obj.business_id
    finally:
        db.close()

    from services.outlook_service import exchange_code_for_tokens
    tokens = exchange_code_for_tokens(code)
    if not tokens:
        return RedirectResponse(url="/dashboard/employees?error=outlook_failed")

    expiry = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))
    db = SessionLocal()
    try:
        update_employee(
            db, employee_id, business_id,
            outlook_access_token=tokens["access_token"],
            outlook_refresh_token=tokens.get("refresh_token"),
            outlook_token_expiry=expiry,
        )
    finally:
        db.close()
    return RedirectResponse(url="/dashboard/employees?success=outlook_connected")
