"""
Routes Stripe : checkout, webhooks, portail client.
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from datetime import datetime
import stripe

from config import settings
from database import SessionLocal, get_business_by_id, update_business, Business
from services.stripe_service import (
    create_checkout_session,
    get_customer_portal_url,
    construct_webhook_event,
)
from services.auth_service import get_current_business_id
from utils import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _get_business_by_customer(db, customer_id: str):
    return db.query(Business).filter(Business.stripe_customer_id == customer_id).first()


@router.get("/subscribe/{plan}")
def subscribe(
    plan: str,
    request: Request,
    business_id: int = Depends(get_current_business_id),
):
    if plan not in ("starter", "pro", "enterprise"):
        raise HTTPException(status_code=400, detail="Plan invalide")

    db = SessionLocal()
    try:
        business = get_business_by_id(db, business_id)
        if not business:
            raise HTTPException(status_code=404)

        success_url = f"{settings.base_url}/dashboard/billing?success=1"
        cancel_url = f"{settings.base_url}/dashboard/billing"

        checkout_url = create_checkout_session(
            business.stripe_customer_id,
            plan,
            business_id,
            success_url,
            cancel_url,
        )

        if not checkout_url:
            logger.warning("Stripe not configured")
            return RedirectResponse(url="/dashboard/billing?success=1", status_code=303)

        return RedirectResponse(url=checkout_url, status_code=303)
    finally:
        db.close()


@router.get("/portal")
def customer_portal(
    request: Request,
    business_id: int = Depends(get_current_business_id),
):
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


def _get_period_end_from_sub(subscription_id: str):
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        ts = sub.get("current_period_end")
        if ts:
            return datetime.utcfromtimestamp(ts)
    except Exception:
        pass
    return None


@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = construct_webhook_event(payload, sig_header)
    except ValueError:
        raise HTTPException(status_code=400, detail="Payload invalide")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Signature invalide")

    event_type = event["type"]
    logger.info("[Stripe webhook] event=%s", event_type)

    db = SessionLocal()
    try:
        if event_type == "checkout.session.completed":
            session = event["data"]["object"]
            business_id = int(session["metadata"].get("business_id", 0))
            plan = session["metadata"].get("plan", "starter")
            subscription_id = session.get("subscription")
            if business_id:
                period_end = _get_period_end_from_sub(subscription_id) if subscription_id else None
                update_business(
                    db, business_id,
                    plan=plan,
                    stripe_subscription_id=subscription_id,
                    subscription_paid=True,
                    subscription_current_period_end=period_end,
                )
                logger.info("[Stripe] business_id=%d activated plan=%s", business_id, plan)

        elif event_type == "invoice.payment_succeeded":
            invoice = event["data"]["object"]
            customer_id = invoice.get("customer")
            billing_reason = invoice.get("billing_reason", "")
            if customer_id and billing_reason in ("subscription_cycle", "subscription_create"):
                business = _get_business_by_customer(db, customer_id)
                if business:
                    sub_id = invoice.get("subscription")
                    period_end = _get_period_end_from_sub(sub_id) if sub_id else None
                    update_business(
                        db, business.id,
                        subscription_paid=True,
                        subscription_current_period_end=period_end,
                    )
                    logger.info("[Stripe] business_id=%d renewed reason=%s", business.id, billing_reason)

        elif event_type == "invoice.payment_failed":
            invoice = event["data"]["object"]
            customer_id = invoice.get("customer")
            if customer_id:
                business = _get_business_by_customer(db, customer_id)
                if business:
                    update_business(db, business.id, subscription_paid=False)
                    logger.warning("[Stripe] business_id=%d payment FAILED blocked", business.id)

        elif event_type == "customer.subscription.updated":
            sub = event["data"]["object"]
            customer_id = sub["customer"]
            business = _get_business_by_customer(db, customer_id)
            if business:
                status = sub.get("status")
                ts = sub.get("current_period_end")
                period_end = datetime.utcfromtimestamp(ts) if ts else None
                if status in ("active", "trialing"):
                    update_business(db, business.id, subscription_paid=True,
                                    subscription_current_period_end=period_end)
                elif status in ("canceled", "unpaid", "past_due"):
                    update_business(db, business.id, subscription_paid=False,
                                    subscription_current_period_end=period_end)
                logger.info("[Stripe] business_id=%d status=%s", business.id, status)

        elif event_type == "customer.subscription.deleted":
            sub = event["data"]["object"]
            customer_id = sub["customer"]
            business = _get_business_by_customer(db, customer_id)
            if business:
                update_business(db, business.id, subscription_paid=False,
                                stripe_subscription_id=None,
                                subscription_current_period_end=None)
                logger.warning("[Stripe] business_id=%d subscription DELETED", business.id)

    finally:
        db.close()

    return {"received": True}
