"""
Gestion des créneaux disponibles.
Calcule les créneaux libres en tenant compte des RDV existants et des horaires d'ouverture.
"""
from datetime import datetime, timedelta, date
from typing import Optional
import pytz
from config import load_business_config, settings


DAY_NAMES_FR_TO_EN = {
    "lundi": "monday",
    "mardi": "tuesday",
    "mercredi": "wednesday",
    "jeudi": "thursday",
    "vendredi": "friday",
    "samedi": "saturday",
    "dimanche": "sunday",
}

DAY_NAMES_EN = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]


def get_service_duration(service_name: str) -> Optional[int]:
    """Retourne la durée en minutes d'un service, ou None si inconnu."""
    config = load_business_config()
    name_lower = service_name.lower().strip()
    for svc in config["services"]:
        if svc["name"].lower() == name_lower:
            return svc["duration"]
    # Fuzzy match
    for svc in config["services"]:
        if name_lower in svc["name"].lower() or svc["name"].lower() in name_lower:
            return svc["duration"]
    return None


def get_available_slots(
    taken_slots: list[tuple[datetime, int]],
    target_date_str: str,
    duration_minutes: int,
    max_slots: int = 8,
) -> list[datetime]:
    """
    Retourne les créneaux disponibles pour une date donnée.

    Args:
        taken_slots: liste de (start_datetime, duration_minutes) déjà pris
        target_date_str: date au format YYYY-MM-DD
        duration_minutes: durée du service souhaité
        max_slots: nombre max de créneaux à retourner

    Returns:
        liste de datetime représentant les créneaux libres
    """
    config = load_business_config()
    tz = pytz.timezone(settings.timezone)

    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    day_en = DAY_NAMES_EN[target_date.weekday()]

    hours = config["working_hours"].get(day_en)
    if not hours:
        return []  # Fermé ce jour

    open_h, open_m = map(int, hours["open"].split(":"))
    close_h, close_m = map(int, hours["close"].split(":"))

    interval = config.get("slot_interval_minutes", 15)

    slot_start = datetime.combine(target_date, datetime.min.time()).replace(
        hour=open_h, minute=open_m, second=0, microsecond=0
    )
    slot_start = tz.localize(slot_start)

    day_end = datetime.combine(target_date, datetime.min.time()).replace(
        hour=close_h, minute=close_m, second=0, microsecond=0
    )
    day_end = tz.localize(day_end)

    now = datetime.now(tz)

    # Normalise taken slots to timezone-aware
    taken = []
    for (start, dur) in taken_slots:
        if start.tzinfo is None:
            start = pytz.utc.localize(start).astimezone(tz)
        else:
            start = start.astimezone(tz)
        taken.append((start, dur))

    available = []
    current = slot_start

    while current + timedelta(minutes=duration_minutes) <= day_end:
        # Pas dans le passé
        if current > now:
            slot_end = current + timedelta(minutes=duration_minutes)
            conflict = False
            for (taken_start, taken_dur) in taken:
                taken_end = taken_start + timedelta(minutes=taken_dur)
                # Vérif chevauchement
                if not (slot_end <= taken_start or current >= taken_end):
                    conflict = True
                    break
            if not conflict:
                available.append(current)
                if len(available) >= max_slots:
                    break

        current += timedelta(minutes=interval)

    return available


def parse_date_fr(date_str: str) -> Optional[str]:
    """
    Tente de parser une date en français.
    Retourne une string 'YYYY-MM-DD' ou None.
    Exemples: "demain", "lundi prochain", "15 mars", "2024-03-15"
    """
    import re
    from datetime import date

    tz = pytz.timezone(settings.timezone)
    today = datetime.now(tz).date()

    date_str = date_str.lower().strip()

    if date_str in ("aujourd'hui", "aujourd hui", "maintenant"):
        return today.strftime("%Y-%m-%d")

    if date_str == "demain":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    if date_str == "après-demain":
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    # "lundi", "mardi", etc. (prochain)
    day_map = {
        "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
        "vendredi": 4, "samedi": 5, "dimanche": 6,
    }
    for day_name, day_num in day_map.items():
        if day_name in date_str:
            days_ahead = (day_num - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # prochain
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    # Format YYYY-MM-DD
    if re.match(r"\d{4}-\d{2}-\d{2}", date_str):
        return date_str

    # "15 mars" ou "15/03"
    mois_map = {
        "janvier": 1, "février": 2, "mars": 3, "avril": 4,
        "mai": 5, "juin": 6, "juillet": 7, "août": 8,
        "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
    }
    for mois_name, mois_num in mois_map.items():
        pattern = rf"(\d{{1,2}})\s+{mois_name}"
        m = re.search(pattern, date_str)
        if m:
            day = int(m.group(1))
            year = today.year
            try:
                d = date(year, mois_num, day)
                if d < today:
                    d = date(year + 1, mois_num, day)
                return d.strftime("%Y-%m-%d")
            except ValueError:
                pass

    # "15/03" ou "15-03"
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?", date_str)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            d = date(year, month, day)
            return d.strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


def format_slots_fr(slots: list[datetime]) -> str:
    """Formate une liste de créneaux en texte français."""
    if not slots:
        return "aucun créneau disponible"
    parts = []
    for slot in slots:
        parts.append(slot.strftime("%Hh%M"))
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " ou " + parts[-1]
