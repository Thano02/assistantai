"""
Utilitaires partagés — helpers, logging, context manager DB, formatage dates.
"""
import logging
import sys
from contextlib import contextmanager
from datetime import datetime
from typing import Generator

import pytz
from sqlalchemy.orm import Session

from config import settings

# ── Logging global ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

logger = get_logger("robot-rdv")


# ── Context manager base de données ───────────────────────────────────────────

@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context manager pour les sessions SQLAlchemy. Rollback automatique en cas d'erreur."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Formatage dates en français ───────────────────────────────────────────────

JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def format_dt_fr(dt: datetime, tz_name: str = None) -> str:
    """
    Formate une datetime en chaîne lisible française.
    Ex: 'lundi 15 mars à 14h30'
    """
    tz = pytz.timezone(tz_name or settings.timezone)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt).astimezone(tz)
    else:
        dt = dt.astimezone(tz)
    return f"{JOURS_FR[dt.weekday()]} {dt.day} {MOIS_FR[dt.month - 1]} à {dt.strftime('%Hh%M')}"


def format_dt_short(dt: datetime, tz_name: str = None) -> str:
    """Format court: '15/03 14:30'"""
    tz = pytz.timezone(tz_name or settings.timezone)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt).astimezone(tz)
    else:
        dt = dt.astimezone(tz)
    return dt.strftime("%d/%m à %Hh%M")


def now_local() -> datetime:
    """Retourne l'heure actuelle dans le fuseau horaire configuré."""
    return datetime.now(pytz.timezone(settings.timezone))


# ── Validation ────────────────────────────────────────────────────────────────

def is_valid_phone(phone: str) -> bool:
    """Vérifie que le numéro ressemble à un format E.164."""
    import re
    return bool(re.match(r"^\+[1-9]\d{6,14}$", phone.strip()))


def is_valid_email(email: str) -> bool:
    """Validation basique d'email."""
    import re
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))
