"""Read-only Google Calendar connector tool for hermit (P1 critical path).

Exposes a single agent tool, ``read_calendar_events``, that reads upcoming
events from the user's Google Calendar. It is *purely read-only*: it returns
events and never writes anything — not to the calendar, not to personal memory.

Division of responsibility (see docs/migration/google-calendar-connector-plan.md):
  - This tool only READS events and returns them.
  - Deciding which events are worth remembering, and staging them, is the
    agent's job via the separate ``propose_memory`` tool (consent-center),
    which routes through human confirmation before anything is persisted.

RED LINE alignment:
  - #3 (don't touch core): new tool under tools/, registered via the public
    registry; no hermes-agent core module is modified.
  - #5 (no silent writes to personal data): reading the calendar is low-risk
    and may be exposed directly; the only writer into personal memory remains
    the consent-center confirm path. Calendar *write* actions (create/delete
    events) are deliberately NOT implemented in this first version.

Credentials are self-contained here (≈ the pattern in the bundled
google-workspace skill's ``google_api.get_credentials``) so this module does
not import the skill scripts (which are CLIs, not importable modules). It reads
the same ``HERMES_HOME/google_token.json`` produced by that skill's setup flow.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from hermes_constants import get_hermes_home
from tools.registry import registry

# Fallback scope if the token file does not record its own scopes. Read-only is
# the principled default for a read tool; in practice the stored scopes (which
# include the broader ``calendar`` scope granted by the bundled skill) are used.
_CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def _token_path():
    """Path to the OAuth token produced by the google-workspace skill setup."""
    return get_hermes_home().expanduser().resolve() / "google_token.json"


def _token_exists() -> bool:
    """``check_fn`` for the toolset: the tool is only usable once authorized."""
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
    the bundled skill scripts. Imports the google libraries lazily so that tool
    discovery never fails if they are absent — ``check_fn`` already gates the
    tool on the token existing, and a missing library surfaces as a clear error
    only when the tool is actually invoked.
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


def _parse_event(raw: dict) -> dict:
    """Project a raw Calendar API event into the fields we expose."""
    start = raw.get("start", {})
    end = raw.get("end", {})
    return {
        "id": raw.get("id", ""),
        "summary": raw.get("summary", "(no title)"),
        "start": start.get("dateTime", start.get("date", "")),
        "end": end.get("dateTime", end.get("date", "")),
        "all_day": "date" in start and "dateTime" not in start,
        "location": raw.get("location", ""),
        "description": raw.get("description", ""),
        "status": raw.get("status", ""),
        "html_link": raw.get("htmlLink", ""),
    }


def read_calendar_events(
    calendar_id: str = "primary",
    days_ahead: int = 7,
    max_results: int = 50,
) -> dict:
    """Read upcoming events from a Google Calendar (read-only).

    Returns a dict. When the user has not authorized yet (no token), returns
    ``{"status": "needs_auth", ...}`` *without* hitting the API, so the agent
    can guide the user through the one-time setup instead of erroring.
    """
    if not _token_exists():
        return {
            "status": "needs_auth",
            "message": (
                "Google Calendar is not authorized yet. Run the one-time setup "
                "in the google-workspace skill: "
                "~/.hermes/skills/productivity/google-workspace/scripts/setup.py "
                "(see docs/migration/google-calendar-connector-plan.md). Once "
                f"{_token_path()} exists, this tool becomes available."
            ),
        }

    now = _now()
    days = max(1, int(days_ahead))
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days)).isoformat()

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

    events = [_parse_event(e) for e in response.get("items", [])]
    return {
        "status": "ok",
        "calendar_id": calendar_id,
        "time_min": time_min,
        "time_max": time_max,
        "event_count": len(events),
        "events": events,
    }


READ_CALENDAR_EVENTS_SCHEMA = {
    "name": "read_calendar_events",
    "description": (
        "Read upcoming events from the user's Google Calendar (READ-ONLY; never "
        "writes). Use this to learn the user's schedule. If you spot something "
        "worth remembering long-term, do NOT persist it yourself — call "
        "propose_memory so a human can confirm it via the consent-center."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "calendar_id": {
                "type": "string",
                "description": "Calendar to read (default 'primary').",
            },
            "days_ahead": {
                "type": "integer",
                "description": "How many days from now to look ahead (default 7).",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of events to return (default 50).",
            },
        },
        "required": [],
    },
}


handler = lambda args, **kw: json.dumps(
    read_calendar_events(
        calendar_id=args.get("calendar_id", "primary"),
        days_ahead=args.get("days_ahead", 7),
        max_results=args.get("max_results", 50),
    ),
    ensure_ascii=False,
)


registry.register(
    name="read_calendar_events",
    toolset="google-calendar",
    schema=READ_CALENDAR_EVENTS_SCHEMA,
    handler=handler,
    check_fn=_token_exists,
    description=(
        "Read upcoming Google Calendar events (read-only). Available only once "
        "the user has authorized via the google-workspace skill setup."
    ),
    emoji="\U0001f4c5",
)
