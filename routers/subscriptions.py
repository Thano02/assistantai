"""
Routes Stripe : checkout, webhooks, portail client.
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
import stripe

from config import settings
from database import SessionLocal, get_business_by_id, update_business
from services.stripe_service import (
    create_checkout_session,
    get_customer_portal_url,
    construct_webhook_event,
)
from services.auth_service import get_current_business_id

router = APIRouter()


@router.get("/subscribe/{plan}")
def subscribe(
    plan: str,
    request: Request,
    business_id: int = Depends(get_current_business_id),
):
    """Redirige vers Stripe Checkout pour souscrire à un plan."""
    if plan not in ("starter", "pro", "enterprise"):
        raise HTTPException(status_code=400, detail="Plan invalide")

    db = SessionLocal()
    try:
        business = get_business_by_id(db, business_id)
        if not business:
            raise HTTPException(status_code=404)

        success_url = f"{settings.base_url}/dashboard/billing?success=1"
        cancel_url = f"{settings.base_url}/pricing"

        checkout_url = create_checkout_session(
            business.stripe_customer_id,
            plan,
            business_id,
            success_url,
            cancel_url,
        )

        if not checkout_url:
            # Stripe non configuré → passer directement en mode test
            update_business(db, business_id, plan=plan)
            return RedirectResponse(url="/dashboard/billing?success=1", status_code=303)

        return RedirectResponse(url=checkout_url, status_code=303)
    finally:
        db.close()


@router.get("/portal")
def customer_portal(
    request: Request,
    business_id: int = Depends(get_current_business_id),
):
    """Redirige vers le portail client Stripe."""
    db = SessionLocal()
    try:
        business = get_business_by_id(db, business_id)
        if not business or not business.stripe_customer_id:
            return RedirectResponse(url="/dashboard/billing")

        return_url = f"{settings.base_url}/dashboard/billing"
        portal_url = get_customer_portal_url(business.stripe_customer_id, return_url)

        if not portal_url:
            return RedirectResponse(url="/dashboard/billing")

        return RedirectResponse(url=portal_url, status_code=303)
    finally:
        db.close()


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Webhook Stripe pour les événements de paiement."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = construct_webhook_event(payload, sig_header)
    except ValueError:
        raise HTTPException(status_code=400, detail="Payload invalide")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Signature invalide")

    db = SessionLocal()
    try:
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            business_id = int(session["metadata"].get("business_id", 0))
            plan = session["metadata"].get("plan", "starter")
            subscription_id = session.get("subscription")
            if business_id:
                update_business(
                    db, business_id,
                    plan=plan,
                    stripe_subscription_id=subscription_id,
                    subscription_paid=True,
                )

        elif event["type"] == "customer.subscription.updated":
            sub = event["data"]["object"]
            customer_id = sub["customer"]
            from database import Business
            business = db.query(Business).filter(
                Business.stripe_customer_id == customer_id
            ).first()
            if business:
                status = sub.get("status")
                if status in ("active", "trialing"):
                    update_business(db, business.id, subscription_paid=True)
                elif status == "canceled":
                    update_business(db, business.id, subscription_paid=False)

        elif event["type"] == "invoice.payment_succeeded":
            invoice = event["data"]["object"]
            business_id_str = invoice.get("metadata", {}).get("business_id")
            if business_id_str:
                from database import MonthlyInvoice
                inv = db.query(MonthlyInvoice).filter(
                    MonthlyInvoice.stripe_invoice_id == invoice["id"]
                ).first()
                if inv:
                    inv.status = "paid"
                    db.commit()

    finally:
        db.close()

    return {"received": True}
