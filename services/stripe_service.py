"""
Service Stripe.
Gère la création des customers, abonnements et factures mensuelles.
"""
try:
    import stripe
except ImportError:
    stripe = None  # type: ignore
from typing import Optional
from config import settings

if stripe:
    stripe.api_key = settings.stripe_secret_key

def create_stripe_customer(email: str, business_name: str) -> Optional[str]:
    """Crée un customer Stripe et retourne son ID."""
    if not settings.stripe_enabled:
        return None
    try:
        customer = stripe.Customer.create(
            email=email,
            name=business_name,
            metadata={"platform": "robot-rdv"},
        )
        return customer.id
    except stripe.StripeError as e:
        print(f"[Stripe] Erreur création customer: {e}")
        return None


def _resolve_price_id() -> Optional[str]:
    """Retourne le price_id Stripe configuré (plan unique 300€/mois)."""
    return settings.stripe_price_id or None


def create_checkout_session(
    customer_id: str,
    plan: str,
    business_id: int,
    success_url: str,
    cancel_url: str,
) -> Optional[str]:
    """Crée une session Stripe Checkout pour l'abonnement. Retourne l'URL de paiement."""
    if not settings.stripe_enabled:
        return None
    price_id = _resolve_price_id()
    if not price_id:
        return None
    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"business_id": str(business_id), "plan": plan},
        )
        return session.url
    except stripe.StripeError as e:
        print(f"[Stripe] Erreur création session checkout: {e}")
        return None


def create_monthly_invoice(
    customer_id: str,
    plan_price_eur: float,
    api_cost_eur: float,
    period_label: str,
    business_name: str,
) -> Optional[str]:
    """
    Crée et finalise une facture Stripe manuelle.
    Retourne l'ID de l'invoice ou None.
    Modèle : plan fixe + coût API × 1.70
    """
    if not settings.stripe_enabled or not customer_id:
        return None
    try:
        # Ligne 1 : abonnement fixe
        stripe.InvoiceItem.create(
            customer=customer_id,
            amount=int(plan_price_eur * 100),  # centimes
            currency="eur",
            description=f"Abonnement Assistant AI — {period_label}",
        )

        # Ligne 2 : consommation API × 1.70
        billed_api = api_cost_eur * 1.70
        if billed_api > 0.50:  # minimum Stripe ~0.50€
            stripe.InvoiceItem.create(
                customer=customer_id,
                amount=int(billed_api * 100),
                currency="eur",
                description=f"Consommation API (coût réel × 1.70) — {period_label}",
            )

        # Créer + finaliser l'invoice
        invoice = stripe.Invoice.create(
            customer=customer_id,
            collection_method="charge_automatically",
            auto_advance=True,
        )
        finalized = stripe.Invoice.finalize_invoice(invoice.id)
        return finalized.id

    except stripe.StripeError as e:
        print(f"[Stripe] Erreur création invoice: {e}")
        return None


def get_customer_portal_url(customer_id: str, return_url: str) -> Optional[str]:
    """Crée un lien vers le portail client Stripe (gérer abonnement, CB, factures)."""
    if not settings.stripe_enabled or not customer_id:
        return None
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return session.url
    except stripe.StripeError as e:
        print(f"[Stripe] Erreur portail client: {e}")
        return None


def construct_webhook_event(payload: bytes, sig_header: str):
    """Valide et construit l'événement webhook Stripe."""
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )


def get_invoice_list(customer_id: str, limit: int = 10) -> list:
    """Retourne les dernières factures d'un customer."""
    if not settings.stripe_enabled or not customer_id:
        return []
    try:
        invoices = stripe.Invoice.list(customer=customer_id, limit=limit)
        return [
            {
                "id": inv.id,
                "amount": inv.amount_paid / 100,
                "currency": inv.currency,
                "status": inv.status,
                "date": inv.created,
                "pdf_url": inv.invoice_pdf,
            }
            for inv in invoices.data
        ]
    except stripe.StripeError:
        return []
