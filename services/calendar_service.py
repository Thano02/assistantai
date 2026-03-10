"""
Intégration Google Calendar.
Synchronise les RDV avec un agenda Google (Gmail ou Workspace).
Pour Outlook: utiliser Microsoft Graph API (configuration séparée).
"""
from datetime import datetime, timedelta
from typing import Optional
import pytz

from config import settings

# Google Calendar scope
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_google_service():
    """Retourne un service Google Calendar authentifié."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    import os
    import pickle

    creds = None
    token_file = "token.pickle"

    if os.path.exists(token_file):
        with open(token_file, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                settings.google_credentials_file, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(token_file, "wb") as token:
            pickle.dump(creds, token)

    return build("calendar", "v3", credentials=creds)


def create_calendar_event(
    client_name: str,
    client_phone: str,
    service_name: str,
    appointment_dt: datetime,
    duration_minutes: int,
) -> Optional[str]:
    """
    Crée un événement dans Google Calendar.
    Retourne l'event_id ou None en cas d'erreur.
    """
    if not settings.google_calendar_enabled:
        return None

    try:
        service = _get_google_service()
        tz = pytz.timezone(settings.timezone)

        if appointment_dt.tzinfo is None:
            appointment_dt = tz.localize(appointment_dt)

        end_dt = appointment_dt + timedelta(minutes=duration_minutes)

        event = {
            "summary": f"{service_name} — {client_name or client_phone}",
            "description": f"RDV pris via Assistant AI\nTél: {client_phone}",
            "start": {
                "dateTime": appointment_dt.isoformat(),
                "timeZone": settings.timezone,
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": settings.timezone,
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 60},
                    {"method": "email", "minutes": 1440},  # 24h
                ],
            },
        }

        created = service.events().insert(
            calendarId=settings.google_calendar_id, body=event
        ).execute()
        return created.get("id")

    except Exception as e:
        print(f"[Calendar] Erreur création événement: {e}")
        return None


def delete_calendar_event(event_id: str) -> bool:
    """Supprime un événement du Google Calendar."""
    if not settings.google_calendar_enabled or not event_id:
        return False
    try:
        service = _get_google_service()
        service.events().delete(
            calendarId=settings.google_calendar_id, eventId=event_id
        ).execute()
        return True
    except Exception as e:
        print(f"[Calendar] Erreur suppression événement: {e}")
        return False


def update_calendar_event(event_id: str, new_dt: datetime, duration_minutes: int) -> bool:
    """Met à jour l'heure d'un événement Google Calendar."""
    if not settings.google_calendar_enabled or not event_id:
        return False
    try:
        service = _get_google_service()
        tz = pytz.timezone(settings.timezone)

        if new_dt.tzinfo is None:
            new_dt = tz.localize(new_dt)

        end_dt = new_dt + timedelta(minutes=duration_minutes)

        event = service.events().get(
            calendarId=settings.google_calendar_id, eventId=event_id
        ).execute()

        event["start"]["dateTime"] = new_dt.isoformat()
        event["end"]["dateTime"] = end_dt.isoformat()

        service.events().update(
            calendarId=settings.google_calendar_id, eventId=event_id, body=event
        ).execute()
        return True
    except Exception as e:
        print(f"[Calendar] Erreur mise à jour événement: {e}")
        return False


def get_calendar_busy_slots(
    date_str: str,
) -> list[tuple[datetime, datetime]]:
    """
    Retourne les plages occupées dans Google Calendar pour une date.
    Utile pour croiser avec les RDV de la DB.
    """
    if not settings.google_calendar_enabled:
        return []

    try:
        from datetime import date
        service = _get_google_service()
        tz = pytz.timezone(settings.timezone)

        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        day_start = tz.localize(datetime.combine(target_date, datetime.min.time()))
        day_end = tz.localize(datetime.combine(target_date, datetime.max.time()))

        events_result = service.events().list(
            calendarId=settings.google_calendar_id,
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        busy = []
        for event in events_result.get("items", []):
            start = event["start"].get("dateTime")
            end = event["end"].get("dateTime")
            if start and end:
                busy.append((
                    datetime.fromisoformat(start),
                    datetime.fromisoformat(end),
                ))
        return busy

    except Exception as e:
        print(f"[Calendar] Erreur lecture créneaux: {e}")
        return []
