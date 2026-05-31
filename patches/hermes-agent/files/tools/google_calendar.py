"""Read-only Google Calendar *source adapter* for hermit's merged calendar.

History: this module originally registered the ``read_calendar_events`` agent
tool directly (commit a321d2f). It has since been demoted to one *source* behind
the merged calendar read: ``calendar_read`` owns the single
``read_calendar_events`` tool and pulls from the native store, ICS caches, and —
when the user has authorized — this Google adapter. Google OAuth is no longer on
the onboarding critical path; ICS subscriptions are the low-friction default.

This module therefore exposes ``fetch_events(...)`` (returning events already in
the unified merged-view schema) and the credential helpers, and deliberately no
longer calls ``registry.register(...)`` — so tool discovery does not surface it
as a standalone tool. ``calendar_read`` imports it explicitly.

It remains *purely read-only*: it returns events and never writes anything — not
to the calendar, not to personal memory. Calendar *write* actions (create/delete
Google events) are deliberately NOT implemented (RED LINE #5). When the user has
not authorized (no token), ``fetch_events`` returns ``[]`` so the merged read
degrades gracefully instead of erroring.

Credentials are self-contained here (≈ the pattern in the bundled
google-workspace skill's ``google_api.get_credentials``); it reads the same
``HERMES_HOME/google_token.json`` produced by that skill's setup flow.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from hermes_constants import get_hermes_home

# Fallback scope if the token file does not record its own scopes. Read-only is
# the principled default for a read tool; in practice the stored scopes (which
# include the broader ``calendar`` scope granted by the bundled skill) are used.
_CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def _token_path():
    """Path to the OAuth token produced by the google-workspace skill setup."""
    return get_hermes_home().expanduser().resolve() / "google_token.json"


def _token_exists() -> bool:
    """Whether Google is authorized; the merged read includes this source only if True."""
    return _token_path().exists()


def _now() -> datetime:
    """Current UTC time. Indirected so tests can pin the time window."""
    return datetime.now(timezone.utc)


def _stored_scopes(token_path) -> list[str]:
    """Scopes recorded in the token file, falling back to read-only calendar."""
    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
    except Exception:
        return [_CALENDAR_READONLY_SCOPE]
    scopes = data.get("scopes")
    if isinstance(scopes, list) and scopes:
        return scopes
    return [_CALENDAR_READONLY_SCOPE]


def _load_credentials():
    """Load credentials from the token file, refreshing + writing back if expired.

    Mirrors ``google_api.get_credentials`` but self-contained: it does not import
    the bundled skill scripts. Imports the google libraries lazily so that import
    of this adapter never fails if they are absent — the token gate already
    prevents fetches without authorization, and a missing library surfaces as a
    clear error only when a fetch is actually attempted.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_path = _token_path()
    creds = Credentials.from_authorized_user_file(
        str(token_path), _stored_scopes(token_path)
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _build_service(creds):
    """Build the Calendar v3 service. Indirected so tests can inject a fake."""
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=creds)


def _parse_event(raw: dict, calendar_id: str = "primary") -> dict:
    """Project a raw Calendar API event into the unified merged-view schema."""
    start = raw.get("start", {})
    end = raw.get("end", {})
    return {
        "id": f"google:{raw.get('id', '')}",
        "title": raw.get("summary", "(no title)"),
        "start": start.get("dateTime", start.get("date", "")),
        "end": end.get("dateTime", end.get("date", "")),
        "all_day": "date" in start and "dateTime" not in start,
        "location": raw.get("location", ""),
        "description": raw.get("description", ""),
        "source": "google",
        "source_ref": {
            "google_id": raw.get("id", ""),
            "calendar_id": calendar_id,
            "html_link": raw.get("htmlLink", ""),
        },
        "status": raw.get("status", ""),
    }


def fetch_events(
    time_min: str | None = None,
    time_max: str | None = None,
    calendar_id: str = "primary",
    max_results: int = 250,
) -> list[dict]:
    """Fetch upcoming Google Calendar events as unified-schema dicts (read-only).

    Returns ``[]`` when the user has not authorized (no token) so the merged
    calendar read can include this source opportunistically without erroring.
    ``time_min``/``time_max`` are ISO-8601 bounds; defaults to now .. now+7d.
    """
    if not _token_exists():
        return []

    now = _now()
    time_min = time_min or now.isoformat()
    time_max = time_max or (now + timedelta(days=7)).isoformat()

    creds = _load_credentials()
    service = _build_service(creds)
    response = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=int(max_results),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    return [_parse_event(e, calendar_id) for e in response.get("items", [])]
