"""
Service Microsoft Outlook Calendar via Microsoft Graph API.
Utilise MSAL pour l'authentification OAuth 2.0.
"""
try:
    import msal
except ImportError:
    msal = None  # type: ignore
import httpx
from datetime import datetime, timedelta
from typing import Optional

from config import settings

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Calendars.ReadWrite", "offline_access"]

# URL de redirect pour OAuth
REDIRECT_URI_PATH = "/auth/outlook-callback"


def get_auth_url(state: str) -> str:
    """Retourne l'URL d'autorisation Microsoft pour rediriger l'utilisateur."""
    authority = f"https://login.microsoftonline.com/{settings.azure_tenant_id}"
    app = msal.ConfidentialClientApplication(
        settings.azure_client_id,
        authority=authority,
        client_credential=settings.azure_client_secret,
    )
    redirect_uri = f"{settings.base_url}{REDIRECT_URI_PATH}"
    auth_url = app.get_authorization_request_url(
        SCOPES,
        state=state,
        redirect_uri=redirect_uri,
    )
    return auth_url


def exchange_code_for_tokens(code: str) -> Optional[dict]:
    """Échange le code OAuth pour des access/refresh tokens."""
    authority = f"https://login.microsoftonline.com/{settings.azure_tenant_id}"
    app = msal.ConfidentialClientApplication(
        settings.azure_client_id,
        authority=authority,
        client_credential=settings.azure_client_secret,
    )
    redirect_uri = f"{settings.base_url}{REDIRECT_URI_PATH}"
    result = app.acquire_token_by_authorization_code(code, SCOPES, redirect_uri=redirect_uri)
    if "access_token" in result:
        return result
    print(f"[Outlook] Erreur échange token: {result.get('error_description')}")
    return None


def refresh_access_token(refresh_token: str) -> Optional[dict]:
    """Rafraîchit le token d'accès expiré."""
    authority = f"https://login.microsoftonline.com/{settings.azure_tenant_id}"
    app = msal.ConfidentialClientApplication(
        settings.azure_client_id,
        authority=authority,
        client_credential=settings.azure_client_secret,
    )
    result = app.acquire_token_by_refresh_token(refresh_token, SCOPES)
    if "access_token" in result:
        return result
    return None


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def create_event(
    access_token: str,
    calendar_id: str,
    subject: str,
    start_dt: datetime,
    end_dt: datetime,
    body: str = "",
    timezone: str = "Europe/Paris",
) -> Optional[str]:
    """Crée un événement dans Outlook Calendar. Retourne l'event ID."""
    url = f"{GRAPH_BASE}/me/calendars/{calendar_id}/events"
    payload = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "start": {
            "dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": timezone,
        },
        "end": {
            "dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": timezone,
        },
    }
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(url, headers=_headers(access_token), json=payload)
            r.raise_for_status()
            return r.json().get("id")
    except Exception as e:
        print(f"[Outlook] Erreur création event: {e}")
        return None


def delete_event(access_token: str, calendar_id: str, event_id: str) -> bool:
    """Supprime un événement Outlook."""
    url = f"{GRAPH_BASE}/me/calendars/{calendar_id}/events/{event_id}"
    try:
        with httpx.Client(timeout=10) as client:
            r = client.delete(url, headers=_headers(access_token))
            return r.status_code == 204
    except Exception as e:
        print(f"[Outlook] Erreur suppression event: {e}")
        return False


def update_event(
    access_token: str,
    calendar_id: str,
    event_id: str,
    start_dt: datetime,
    end_dt: datetime,
    timezone: str = "Europe/Paris",
) -> bool:
    """Met à jour l'heure d'un événement Outlook."""
    url = f"{GRAPH_BASE}/me/calendars/{calendar_id}/events/{event_id}"
    payload = {
        "start": {
            "dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": timezone,
        },
        "end": {
            "dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": timezone,
        },
    }
    try:
        with httpx.Client(timeout=10) as client:
            r = client.patch(url, headers=_headers(access_token), json=payload)
            return r.status_code == 200
    except Exception as e:
        print(f"[Outlook] Erreur mise à jour event: {e}")
        return False


def get_events(
    access_token: str,
    calendar_id: str,
    start_dt: datetime,
    end_dt: datetime,
) -> list[dict]:
    """Récupère les événements Outlook sur une plage de dates."""
    url = (
        f"{GRAPH_BASE}/me/calendars/{calendar_id}/calendarView"
        f"?startDateTime={start_dt.isoformat()}Z&endDateTime={end_dt.isoformat()}Z"
        f"&$select=id,subject,start,end&$top=100"
    )
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(url, headers=_headers(access_token))
            r.raise_for_status()
            return r.json().get("value", [])
    except Exception as e:
        print(f"[Outlook] Erreur lecture events: {e}")
        return []


def get_user_calendars(access_token: str) -> list[dict]:
    """Liste les calendriers disponibles pour l'utilisateur."""
    url = f"{GRAPH_BASE}/me/calendars?$select=id,name,isDefaultCalendar"
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(url, headers=_headers(access_token))
            r.raise_for_status()
            return r.json().get("value", [])
    except Exception as e:
        print(f"[Outlook] Erreur liste calendriers: {e}")
        return []
