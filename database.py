from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Float,
    ForeignKey, Enum, Text, Boolean
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from datetime import datetime
import enum
from config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─── BUSINESS (tenant SaaS) ──────────────────────────────────────────────────

class Business(Base):
    __tablename__ = "businesses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    owner_email = Column(String(200), unique=True, index=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    plan = Column(String(20), default="starter")   # starter | pro | enterprise
    is_active = Column(Boolean, default=True)

    # Stripe
    stripe_customer_id = Column(String(100), nullable=True)
    stripe_subscription_id = Column(String(100), nullable=True)

    # Twilio (par commerce)
    twilio_phone_number = Column(String(20), nullable=True)
    twilio_account_sid = Column(String(50), nullable=True)
    twilio_auth_token = Column(String(50), nullable=True)

    # ElevenLabs (par commerce — optionnel, sinon utilise le global)
    elevenlabs_voice_id = Column(String(100), nullable=True)

    # Google Calendar OAuth tokens
    google_calendar_id = Column(String(200), nullable=True)
    google_access_token = Column(Text, nullable=True)
    google_refresh_token = Column(Text, nullable=True)
    google_token_expiry = Column(DateTime, nullable=True)

    # Outlook OAuth tokens (MSAL)
    outlook_calendar_id = Column(String(200), nullable=True)
    outlook_access_token = Column(Text, nullable=True)
    outlook_refresh_token = Column(Text, nullable=True)
    outlook_token_expiry = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    # Super admin
    is_superadmin = Column(Boolean, default=False)

    # Email verification
    email_verified = Column(Boolean, default=False)
    email_verification_token = Column(String(100), nullable=True)

    # Paiement (géré manuellement par le superadmin)
    subscription_paid = Column(Boolean, default=True)

    # Profession & configuration
    profession_type = Column(String(30), default="salon")
    # "ask" = robot propose le choix | "auto" = premier disponible
    employee_selection_enabled = Column(Boolean, default=False)


class OAuthState(Base):
    """Stockage des states OAuth (remplace le dict en mémoire)."""
    __tablename__ = "oauth_states"

    id = Column(Integer, primary_key=True, index=True)
    state_key = Column(String(100), unique=True, index=True, nullable=False)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    employee_id = Column(Integer, nullable=True)  # si OAuth pour un employé
    expires_at = Column(DateTime, nullable=False)


class Employee(Base):
    """Employé d'un commerce (coiffeur, esthéticienne, etc.)."""
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    specialty = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)

    # Google Calendar OAuth
    google_calendar_id = Column(String(200), nullable=True)
    google_access_token = Column(Text, nullable=True)
    google_refresh_token = Column(Text, nullable=True)
    google_token_expiry = Column(DateTime, nullable=True)

    # Outlook OAuth
    outlook_calendar_id = Column(String(200), nullable=True)
    outlook_access_token = Column(Text, nullable=True)
    outlook_refresh_token = Column(Text, nullable=True)
    outlook_token_expiry = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class FAQ(Base):
    """Base de questions/réponses fréquentes par commerce."""
    __tablename__ = "faqs"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    question = Column(String(500), nullable=False)
    answer = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    event_type = Column(String(30), nullable=False)
    # event_type: gpt_input | gpt_output | tts_chars | twilio_voice_min | twilio_sms
    quantity = Column(Float, default=0.0)
    cost_eur = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class MonthlyInvoice(Base):
    __tablename__ = "monthly_invoices"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    api_cost_eur = Column(Float, default=0.0)
    markup_eur = Column(Float, default=0.0)      # api_cost × 0.70
    plan_price_eur = Column(Float, default=0.0)
    total_eur = Column(Float, default=0.0)
    stripe_invoice_id = Column(String(100), nullable=True)
    status = Column(String(20), default="pending")  # pending | paid | failed
    created_at = Column(DateTime, default=datetime.utcnow)


# ─── RESERVATION STATUS ───────────────────────────────────────────────────────

class ReservationStatus(str, enum.Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    MODIFIED = "modified"
    COMPLETED = "completed"


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=True, index=True)
    phone_number = Column(String(20), index=True, nullable=False)
    name = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_call_at = Column(DateTime, nullable=True)
    total_reservations = Column(Integer, default=0)


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    service_name = Column(String(100), nullable=False)
    appointment_dt = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, default=30)
    status = Column(Enum(ReservationStatus), default=ReservationStatus.CONFIRMED)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    employee_name = Column(String(100), nullable=True)  # snapshot
    google_event_id = Column(String(200), nullable=True)
    reminder_sent = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ContactRequest(Base):
    __tablename__ = "contact_requests"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(200), nullable=False)
    phone = Column(String(30), nullable=True)
    project_description = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise


# ─── CLIENT CRUD ────────────────────────────────────────────────────────────

def get_or_create_client(db: Session, phone_number: str) -> Client:
    client = db.query(Client).filter(Client.phone_number == phone_number).first()
    if not client:
        client = Client(phone_number=phone_number)
        db.add(client)
        db.commit()
        db.refresh(client)
    return client


def update_client_name(db: Session, phone_number: str, name: str) -> Client:
    client = db.query(Client).filter(Client.phone_number == phone_number).first()
    if client:
        client.name = name
        db.commit()
        db.refresh(client)
    return client


def update_client_last_call(db: Session, phone_number: str):
    client = db.query(Client).filter(Client.phone_number == phone_number).first()
    if client:
        client.last_call_at = datetime.utcnow()
        db.commit()


# ─── RESERVATION CRUD ───────────────────────────────────────────────────────

def get_upcoming_reservations(db: Session, phone_number: str) -> list[Reservation]:
    client = db.query(Client).filter(Client.phone_number == phone_number).first()
    if not client:
        return []
    now = datetime.utcnow()
    return (
        db.query(Reservation)
        .filter(
            Reservation.client_id == client.id,
            Reservation.appointment_dt > now,
            Reservation.status == ReservationStatus.CONFIRMED,
        )
        .order_by(Reservation.appointment_dt)
        .all()
    )


def get_reservations_needing_reminder(db: Session) -> list[tuple[Reservation, Client]]:
    """Returns reservations in ~24h that haven't had a reminder sent."""
    from datetime import timedelta
    now = datetime.utcnow()
    tomorrow_start = now + timedelta(hours=23)
    tomorrow_end = now + timedelta(hours=25)
    results = (
        db.query(Reservation, Client)
        .join(Client, Reservation.client_id == Client.id)
        .filter(
            Reservation.appointment_dt >= tomorrow_start,
            Reservation.appointment_dt <= tomorrow_end,
            Reservation.status == ReservationStatus.CONFIRMED,
            Reservation.reminder_sent == False,
        )
        .all()
    )
    return results


def create_reservation(
    db: Session,
    phone_number: str,
    service_name: str,
    appointment_dt: datetime,
    duration_minutes: int,
    google_event_id: str = None,
    employee_id: int = None,
    employee_name: str = None,
    business_id: int = None,
) -> Reservation:
    client = get_or_create_client(db, phone_number)
    reservation = Reservation(
        client_id=client.id,
        service_name=service_name,
        appointment_dt=appointment_dt,
        duration_minutes=duration_minutes,
        google_event_id=google_event_id,
        employee_id=employee_id,
        employee_name=employee_name,
        business_id=business_id,
    )
    db.add(reservation)
    client.total_reservations += 1
    db.commit()
    db.refresh(reservation)
    return reservation


def cancel_reservation(db: Session, reservation_id: int) -> Reservation:
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if reservation:
        reservation.status = ReservationStatus.CANCELLED
        db.commit()
        db.refresh(reservation)
    return reservation


def modify_reservation(
    db: Session, reservation_id: int, new_dt: datetime
) -> Reservation:
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if reservation:
        reservation.appointment_dt = new_dt
        reservation.status = ReservationStatus.CONFIRMED
        reservation.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(reservation)
    return reservation


def get_taken_slots(db: Session, date_str: str) -> list[tuple[datetime, int]]:
    """Returns list of (start_datetime, duration_minutes) for confirmed reservations on a date."""
    from datetime import date
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = datetime.combine(target_date, datetime.max.time())
    reservations = (
        db.query(Reservation)
        .filter(
            Reservation.appointment_dt >= day_start,
            Reservation.appointment_dt <= day_end,
            Reservation.status == ReservationStatus.CONFIRMED,
        )
        .all()
    )
    return [(r.appointment_dt, r.duration_minutes) for r in reservations]


def mark_reminder_sent(db: Session, reservation_id: int):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if reservation:
        reservation.reminder_sent = True
        db.commit()


# ─── BUSINESS CRUD ───────────────────────────────────────────────────────────

def get_business_by_email(db: Session, email: str) -> Business:
    return db.query(Business).filter(Business.owner_email == email).first()


def get_business_by_id(db: Session, business_id: int) -> Business:
    return db.query(Business).filter(Business.id == business_id).first()


def create_business(
    db: Session,
    name: str,
    owner_email: str,
    password_hash: str,
    plan: str = "starter",
) -> Business:
    business = Business(
        name=name,
        owner_email=owner_email,
        password_hash=password_hash,
        plan=plan,
    )
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


def update_business(db: Session, business_id: int, **kwargs) -> Business:
    business = db.query(Business).filter(Business.id == business_id).first()
    if business:
        for key, value in kwargs.items():
            setattr(business, key, value)
        db.commit()
        db.refresh(business)
    return business


# ─── USAGE TRACKING ──────────────────────────────────────────────────────────

def log_usage(
    db: Session,
    business_id: int,
    event_type: str,
    quantity: float,
    cost_eur: float,
):
    log = UsageLog(
        business_id=business_id,
        event_type=event_type,
        quantity=quantity,
        cost_eur=cost_eur,
    )
    db.add(log)
    db.commit()


def get_monthly_usage(db: Session, business_id: int, year: int, month: int) -> dict:
    from datetime import date
    from sqlalchemy import func, extract
    period_start = datetime(year, month, 1)
    if month == 12:
        period_end = datetime(year + 1, 1, 1)
    else:
        period_end = datetime(year, month + 1, 1)

    results = (
        db.query(UsageLog.event_type, func.sum(UsageLog.cost_eur).label("total_cost"))
        .filter(
            UsageLog.business_id == business_id,
            UsageLog.created_at >= period_start,
            UsageLog.created_at < period_end,
        )
        .group_by(UsageLog.event_type)
        .all()
    )
    total = sum(r.total_cost for r in results)
    return {
        "period": f"{year}-{month:02d}",
        "breakdown": {r.event_type: round(r.total_cost, 4) for r in results},
        "api_cost_eur": round(total, 4),
        "billed_eur": round(total * 1.70, 2),
    }


def get_all_active_businesses(db: Session) -> list[Business]:
    return db.query(Business).filter(Business.is_active == True).all()


# ─── EMPLOYEE CRUD ───────────────────────────────────────────────────────────

def get_employees(db: Session, business_id: int) -> list[Employee]:
    return db.query(Employee).filter(
        Employee.business_id == business_id,
        Employee.is_active == True
    ).all()


def get_employee_by_id(db: Session, employee_id: int, business_id: int) -> Employee:
    return db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.business_id == business_id
    ).first()


def create_employee(db: Session, business_id: int, name: str, specialty: str = None) -> Employee:
    employee = Employee(business_id=business_id, name=name, specialty=specialty)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def update_employee(db: Session, employee_id: int, business_id: int, **kwargs) -> Employee:
    employee = get_employee_by_id(db, employee_id, business_id)
    if employee:
        for key, value in kwargs.items():
            setattr(employee, key, value)
        db.commit()
        db.refresh(employee)
    return employee


def deactivate_employee(db: Session, employee_id: int, business_id: int) -> bool:
    employee = get_employee_by_id(db, employee_id, business_id)
    if employee:
        employee.is_active = False
        db.commit()
        return True
    return False


# ─── FAQ CRUD ────────────────────────────────────────────────────────────────

def get_faqs(db: Session, business_id: int) -> list[FAQ]:
    return (
        db.query(FAQ)
        .filter(FAQ.business_id == business_id, FAQ.is_active == True)
        .order_by(FAQ.order_index)
        .all()
    )


def create_faq(db: Session, business_id: int, question: str, answer: str, order_index: int = 0) -> FAQ:
    faq = FAQ(business_id=business_id, question=question, answer=answer, order_index=order_index)
    db.add(faq)
    db.commit()
    db.refresh(faq)
    return faq


def update_faq(db: Session, faq_id: int, business_id: int, **kwargs) -> FAQ:
    faq = db.query(FAQ).filter(FAQ.id == faq_id, FAQ.business_id == business_id).first()
    if faq:
        for key, value in kwargs.items():
            setattr(faq, key, value)
        db.commit()
        db.refresh(faq)
    return faq


def delete_faq(db: Session, faq_id: int, business_id: int) -> bool:
    faq = db.query(FAQ).filter(FAQ.id == faq_id, FAQ.business_id == business_id).first()
    if faq:
        faq.is_active = False
        db.commit()
        return True
    return False


def bulk_create_faqs(db: Session, business_id: int, items: list[dict]) -> list[FAQ]:
    faqs = []
    for i, item in enumerate(items):
        faq = FAQ(
            business_id=business_id,
            question=item["question"],
            answer=item["answer"],
            order_index=i,
        )
        db.add(faq)
        faqs.append(faq)
    db.commit()
    return faqs


# ─── OAUTH STATE CRUD ────────────────────────────────────────────────────────

def save_oauth_state(db: Session, state_key: str, business_id: int, employee_id: int = None, ttl_seconds: int = 600):
    from datetime import timedelta
    expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
    existing = db.query(OAuthState).filter(OAuthState.state_key == state_key).first()
    if existing:
        existing.expires_at = expires_at
        existing.business_id = business_id
        existing.employee_id = employee_id
    else:
        db.add(OAuthState(state_key=state_key, business_id=business_id, employee_id=employee_id, expires_at=expires_at))
    db.commit()


def pop_oauth_state(db: Session, state_key: str) -> OAuthState | None:
    state = db.query(OAuthState).filter(OAuthState.state_key == state_key).first()
    if state:
        if state.expires_at < datetime.utcnow():
            db.delete(state)
            db.commit()
            return None
        db.delete(state)
        db.commit()
        return state
    return None


def cleanup_expired_oauth_states(db: Session):
    db.query(OAuthState).filter(OAuthState.expires_at < datetime.utcnow()).delete()
    db.commit()


def save_monthly_invoice(
    db: Session,
    business_id: int,
    period_start: datetime,
    period_end: datetime,
    api_cost_eur: float,
    plan_price_eur: float,
    stripe_invoice_id: str = None,
) -> MonthlyInvoice:
    markup = api_cost_eur * 0.70
    total = plan_price_eur + api_cost_eur + markup
    invoice = MonthlyInvoice(
        business_id=business_id,
        period_start=period_start,
        period_end=period_end,
        api_cost_eur=api_cost_eur,
        markup_eur=markup,
        plan_price_eur=plan_price_eur,
        total_eur=total,
        stripe_invoice_id=stripe_invoice_id,
        status="pending",
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice
