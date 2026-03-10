"""
Routes d'authentification : inscription, connexion, déconnexion, OAuth calendriers.
"""
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Form, Request, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from database import (
    SessionLocal,
    get_business_by_email,
    create_business,
    update_business,
    save_oauth_state,
    pop_oauth_state,
)
from services.auth_service import hash_password, verify_password, create_access_token, get_current_business_id
from services.stripe_service import create_stripe_customer
from services.outlook_service import get_auth_url as outlook_auth_url, exchange_code_for_tokens
from services.email_service import send_verification_email, send_welcome_email
from utils import get_logger

logger = get_logger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")


# ── Inscription ───────────────────────────────────────────────────────────────

@router.get("/register")
def register_page(request: Request, plan: str = "starter"):
    return templates.TemplateResponse("register.html", {"request": request, "error": None, "plan": plan})


@router.post("/register")
def register_submit(
    request: Request,
    business_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    plan: str = Form("starter"),
):
    db = SessionLocal()
    try:
        if get_business_by_email(db, email):
            return templates.TemplateResponse(
                "register.html",
                {"request": request, "error": "Cet email est déjà utilisé.", "plan": plan},
            )

        pw_hash = hash_password(password)
        verification_token = uuid.uuid4().hex
        business = create_business(db, business_name, email, pw_hash, plan)
        update_business(
            db, business.id,
            email_verification_token=verification_token,
            email_verified=False,
        )

        # Stripe customer
        stripe_id = create_stripe_customer(email, business_name)
        if stripe_id:
            update_business(db, business.id, stripe_customer_id=stripe_id)

        # Send verification email
        send_verification_email(email, verification_token, business_name)

        return RedirectResponse(url="/auth/check-email", status_code=303)
    finally:
        db.close()


# ── Email verification ────────────────────────────────────────────────────────

@router.get("/check-email")
def check_email_page(request: Request):
    return templates.TemplateResponse("check_email.html", {"request": request})


@router.get("/verify-email/{token}")
def verify_email(request: Request, token: str):
    db = SessionLocal()
    try:
        from database import Business
        business = db.query(Business).filter(
            Business.email_verification_token == token,
            Business.email_verified == False,
        ).first()

        if not business:
            return templates.TemplateResponse(
                "check_email.html",
                {"request": request, "error": "Lien invalide ou déjà utilisé."},
            )

        update_business(
            db, business.id,
            email_verified=True,
            email_verification_token=None,
        )
        send_welcome_email(business.owner_email, business.name)

        return RedirectResponse(url="/auth/login?verified=1", status_code=303)
    finally:
        db.close()


@router.get("/resend-verification")
def resend_verification(request: Request):
    """Re-send verification email. Rate-limited client-side."""
    # We need the email — read from cookie token if present
    from services.auth_service import decode_token
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/auth/check-email", status_code=303)

    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/auth/login", status_code=303)

    db = SessionLocal()
    try:
        business = get_business_by_email(db, payload["email"])
        if not business or business.email_verified:
            return RedirectResponse(url="/dashboard", status_code=303)

        new_token = uuid.uuid4().hex
        update_business(db, business.id, email_verification_token=new_token)
        send_verification_email(business.owner_email, new_token, business.name)
        return RedirectResponse(url="/auth/check-email?resent=1", status_code=303)
    finally:
        db.close()


# ── Connexion ─────────────────────────────────────────────────────────────────

@router.get("/login")
def login_page(request: Request, error: str = None, verified: str = None):
    return templates.TemplateResponse("login.html", {"request": request, "error": error, "verified": verified})


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    db = SessionLocal()
    try:
        business = get_business_by_email(db, email)
        if not business or not verify_password(password, business.password_hash):
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Email ou mot de passe incorrect."},
            )

        if not business.email_verified:
            # Set a temporary cookie so resend can identify the user
            jwt_token = create_access_token(business.id, email)
            response = RedirectResponse(url="/auth/check-email", status_code=303)
            response.set_cookie(
                "access_token", jwt_token,
                httponly=True, max_age=60 * 60 * 24 * 30, samesite="lax",
            )
            return response

        update_business(db, business.id, last_login_at=datetime.utcnow())

        jwt_token = create_access_token(business.id, email)
        redirect_url = "/superadmin/dashboard" if business.is_superadmin else "/dashboard"
        response = RedirectResponse(url=redirect_url, status_code=303)
        response.set_cookie(
            "access_token", jwt_token,
            httponly=True, max_age=60 * 60 * 24 * 30, samesite="lax",
        )
        return response
    finally:
        db.close()


# ── Déconnexion ───────────────────────────────────────────────────────────────

@router.get("/logout")
def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("access_token")
    return response


# ── Google Calendar OAuth ─────────────────────────────────────────────────────

@router.get("/google-calendar")
def google_calendar_connect(business_id: int = Depends(get_current_business_id)):
    from config import settings
    state = secrets.token_urlsafe(16)
    db = SessionLocal()
    try:
        save_oauth_state(db, state, business_id)
    finally:
        db.close()

    redirect_uri = f"{settings.base_url}/auth/google-callback"
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


@router.get("/google-callback")
def google_calendar_callback(code: str = None, state: str = None, error: str = None):
    if error or not code or not state:
        return RedirectResponse(url="/dashboard/settings?error=google_cancelled")

    db = SessionLocal()
    try:
        state_obj = pop_oauth_state(db, state)
        if not state_obj:
            return RedirectResponse(url="/dashboard/settings?error=invalid_state")
        business_id = state_obj.business_id
    finally:
        db.close()

    from config import settings
    import httpx

    redirect_uri = f"{settings.base_url}/auth/google-callback"
    try:
        with httpx.Client() as client:
            r = client.post("https://oauth2.googleapis.com/token", data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
            r.raise_for_status()
            tokens = r.json()

        expiry = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))
        db = SessionLocal()
        try:
            update_business(
                db, business_id,
                google_access_token=tokens["access_token"],
                google_refresh_token=tokens.get("refresh_token"),
                google_token_expiry=expiry,
            )
        finally:
            db.close()

        return RedirectResponse(url="/dashboard/settings?success=google_connected")
    except Exception as e:
        logger.error("Google OAuth error: %s", e)
        return RedirectResponse(url="/dashboard/settings?error=google_failed")


# ── Outlook OAuth ─────────────────────────────────────────────────────────────

@router.get("/outlook")
def outlook_connect(business_id: int = Depends(get_current_business_id)):
    state = secrets.token_urlsafe(16)
    db = SessionLocal()
    try:
        save_oauth_state(db, state, business_id)
    finally:
        db.close()
    return RedirectResponse(url=outlook_auth_url(state))


@router.get("/outlook-callback")
def outlook_callback(code: str = None, state: str = None, error: str = None):
    if error or not code or not state:
        return RedirectResponse(url="/dashboard/settings?error=outlook_cancelled")

    db = SessionLocal()
    try:
        state_obj = pop_oauth_state(db, state)
        if not state_obj:
            return RedirectResponse(url="/dashboard/settings?error=invalid_state")
        business_id = state_obj.business_id
    finally:
        db.close()

    tokens = exchange_code_for_tokens(code)
    if not tokens:
        return RedirectResponse(url="/dashboard/settings?error=outlook_failed")

    expiry = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))
    db = SessionLocal()
    try:
        update_business(
            db, business_id,
            outlook_access_token=tokens["access_token"],
            outlook_refresh_token=tokens.get("refresh_token"),
            outlook_token_expiry=expiry,
        )
    finally:
        db.close()

    return RedirectResponse(url="/dashboard/settings?success=outlook_connected")
