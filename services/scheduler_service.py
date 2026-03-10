"""
Planificateur de tâches en arrière-plan.
Gère l'envoi automatique des SMS de rappel 24h avant les RDV.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import pytz
from config import settings


_scheduler = BackgroundScheduler(timezone=settings.timezone)


def _send_reminders():
    """Tâche planifiée : envoie les SMS de rappel pour les RDV dans ~24h."""
    from database import SessionLocal, get_reservations_needing_reminder, mark_reminder_sent
    from services.sms_service import send_reminder_sms

    db = SessionLocal()
    try:
        pending = get_reservations_needing_reminder(db)
        for reservation, client in pending:
            success = send_reminder_sms(
                to_number=client.phone_number,
                client_name=client.name or "",
                service_name=reservation.service_name,
                appointment_dt=reservation.appointment_dt,
                reservation_id=reservation.id,
            )
            if success:
                mark_reminder_sent(db, reservation.id)
                print(f"[Scheduler] Rappel SMS envoyé → {client.phone_number} pour RDV #{reservation.id}")
    except Exception as e:
        print(f"[Scheduler] Erreur envoi rappels: {e}")
    finally:
        db.close()


def _cleanup_audio():
    """Tâche planifiée : nettoie les vieux fichiers audio."""
    from services.tts_service import cleanup_old_audio
    cleanup_old_audio(max_age_seconds=3600)


def _generate_monthly_invoices():
    """
    Tâche planifiée le 1er de chaque mois.
    Crée les factures Stripe pour tous les commerces actifs.
    """
    from datetime import datetime, timedelta
    from database import SessionLocal, get_all_active_businesses, get_monthly_usage, save_monthly_invoice
    from services.stripe_service import create_monthly_invoice
    from config import settings

    tz = pytz.timezone(settings.timezone)
    now = datetime.now(tz)

    # Mois précédent
    if now.month == 1:
        year, month = now.year - 1, 12
    else:
        year, month = now.year, now.month - 1

    period_start = datetime(year, month, 1)
    if month == 12:
        period_end = datetime(year + 1, 1, 1)
    else:
        period_end = datetime(year, month + 1, 1)

    db = SessionLocal()
    try:
        businesses = get_all_active_businesses(db)
        for business in businesses:
            usage = get_monthly_usage(db, business.id, year, month)
            api_cost = usage.get("api_cost_eur", 0.0)
            plan_price = settings.plan_prices.get(business.plan, 29.0)
            period_label = f"{year}-{month:02d}"

            stripe_invoice_id = create_monthly_invoice(
                business.stripe_customer_id,
                plan_price,
                api_cost,
                period_label,
                business.name,
            )

            save_monthly_invoice(
                db, business.id,
                period_start, period_end,
                api_cost, plan_price,
                stripe_invoice_id,
            )
            print(f"[Scheduler] Facture {period_label} créée pour {business.name}")
    except Exception as e:
        print(f"[Scheduler] Erreur génération factures: {e}")
    finally:
        db.close()


def start_scheduler():
    if not _scheduler.running:
        # Vérification des rappels toutes les 30 minutes
        _scheduler.add_job(
            _send_reminders,
            trigger=IntervalTrigger(minutes=30),
            id="send_reminders",
            replace_existing=True,
        )
        # Nettoyage audio toutes les heures
        _scheduler.add_job(
            _cleanup_audio,
            trigger=IntervalTrigger(hours=1),
            id="cleanup_audio",
            replace_existing=True,
        )
        # Facturation mensuelle — le 1er de chaque mois à 8h00
        from apscheduler.triggers.cron import CronTrigger
        _scheduler.add_job(
            _generate_monthly_invoices,
            trigger=CronTrigger(day=1, hour=8, minute=0, timezone=settings.timezone),
            id="monthly_invoices",
            replace_existing=True,
        )
        _scheduler.start()
        print("[Scheduler] Démarré (rappels SMS + nettoyage audio + facturation mensuelle)")


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        print("[Scheduler] Arrêté")
