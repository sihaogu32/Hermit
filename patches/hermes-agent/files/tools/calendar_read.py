"""Merged calendar read + event-proposal agent tools (toolset ``calendar``).

This module owns the single agent-facing ``read_calendar_events`` tool, which
returns a *merged view* over hermit's calendar sources:

  ① native events       — owned by hermit (``calendar_store``), always present
  ② ICS subscriptions   — read-only mirrors (deferred; interface stubbed here)
  ③ Google adapter      — read-only, included only when the user has authorized

It also exposes ``propose_event``: the agent stages candidate events (never
writes the calendar) for human confirmation via the consent-center, which on
confirm routes to ``consent_event.apply_event`` (see that module).

RED LINE alignment:
  - #3: a plain ``tools/`` module registered via the public registry; no core
    module is modified. The Google source is imported explicitly (it no longer
    self-registers).
  - #5: ``read_calendar_events`` is read-only; ``propose_event`` only stages.
    Nothing here writes personal data directly.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from tools.registry import registry
from tools import calendar_store, consent_event, google_calendar


def _now() -> datetime:
    """Current UTC time. Indirected so tests can pin the window."""
    return datetime.now(timezone.utc)


def _window(days_ahead: int) -> tuple[str, str]:
    now = _now()
    days = max(1, int(days_ahead))
    return now.isoformat(), (now + timedelta(days=days)).isoformat()


def _ics_events(time_min: str, time_max: str) -> list[dict]:
    """ICS subscription occurrences within the window.

    Deferred to the ICS slice (needs ``icalendar``); returns no events for now so
    the merged read works today without that dependency. Failures here must
    degrade to ``[]`` and never break the merged read.
    """
    return []


def merged_events(
    time_min: str,
    time_max: str,
    calendar_id: str = "primary",
    max_results: int = 250,
) -> dict:
    """Merged view over native + ICS + Google sources for an explicit window.

    Read-only. Native events are always included; ICS and Google are included
    opportunistically and degrade to nothing when absent/unauthorized, so this
    never errors on a fresh install. Events are returned sorted by start time.
    Used both by the agent tool (relative window) and the dashboard (arbitrary
    month/week window).
    """
    native = calendar_store.list_events(start=time_min, end=time_max)

    try:
        google = google_calendar.fetch_events(
            time_min=time_min, time_max=time_max,
            calendar_id=calendar_id, max_results=max_results,
        )
    except Exception:
        google = []  # a Google failure must not break the merged read

    ics = _ics_events(time_min, time_max)

    merged = [*native, *ics, *google]
    merged.sort(key=calendar_store._sort_key)
    if max_results and len(merged) > int(max_results):
        merged = merged[: int(max_results)]

    return {
        "status": "ok",
        "time_min": time_min,
        "time_max": time_max,
        "event_count": len(merged),
        "sources": {
            "native": len(native),
            "ics": len(ics),
            "google": len(google),
        },
        "events": merged,
    }


def read_calendar_events(
    days_ahead: int = 7,
    max_results: int = 250,
    calendar_id: str = "primary",
) -> dict:
    """Agent-facing merged read over a relative window (now .. now+days_ahead)."""
    time_min, time_max = _window(days_ahead)
    return merged_events(time_min, time_max, calendar_id=calendar_id, max_results=max_results)


READ_CALENDAR_EVENTS_SCHEMA = {
    "name": "read_calendar_events",
    "description": (
        "Read upcoming events as a MERGED VIEW across the user's calendar "
        "sources: hermit's own native events, ICS subscriptions, and (if "
        "authorized) Google Calendar. READ-ONLY; never writes. To add an event, "
        "do NOT write it yourself — call propose_event so a human can confirm it "
        "via the consent-center. Each event is tagged with its 'source'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "description": "How many days from now to look ahead (default 7).",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of events to return (default 250).",
            },
            "calendar_id": {
                "type": "string",
                "description": "Google calendar to include if authorized (default 'primary').",
            },
        },
        "required": [],
    },
}

PROPOSE_EVENT_SCHEMA = {
    "name": "propose_event",
    "description": (
        "Stage one or more calendar events for the user to confirm. This does "
        "NOT write the calendar — it places the events in the consent-center "
        "review area; the user confirms each before it lands in their calendar. "
        "Use this whenever you want to add something to the user's schedule."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "Candidate events to stage for human confirmation.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Event title. Required."},
                        "start": {
                            "type": "string",
                            "description": "ISO-8601 start (e.g. '2026-06-02T09:00:00+08:00' or '2026-06-05' for all-day). Required.",
                        },
                        "end": {"type": "string", "description": "ISO-8601 end. Optional (defaults to start)."},
                        "all_day": {"type": "boolean", "description": "True for all-day events. Optional."},
                        "location": {"type": "string", "description": "Optional location."},
                        "description": {"type": "string", "description": "Optional details."},
                    },
                    "required": ["title", "start"],
                },
            },
            "source": {
                "type": "string",
                "description": "Where this proposal came from (default 'agent').",
            },
            "source_ref": {
                "type": "object",
                "description": "Optional reference back to the originating record.",
            },
        },
        "required": ["items"],
    },
}


read_handler = lambda args, **kw: json.dumps(
    read_calendar_events(
        days_ahead=args.get("days_ahead", 7),
        max_results=args.get("max_results", 250),
        calendar_id=args.get("calendar_id", "primary"),
    ),
    ensure_ascii=False,
)

propose_handler = lambda args, **kw: json.dumps(
    consent_event.propose_event(
        items=args.get("items", []),
        source=args.get("source", "agent"),
        source_ref=args.get("source_ref"),
    ),
    ensure_ascii=False,
)


registry.register(
    name="read_calendar_events",
    toolset="calendar",
    schema=READ_CALENDAR_EVENTS_SCHEMA,
    handler=read_handler,
    description=(
        "Read upcoming events as a merged view over native + ICS + Google "
        "sources (read-only). Always available; external sources are included "
        "only when present/authorized."
    ),
    emoji="\U0001f4c5",
)

registry.register(
    name="propose_event",
    toolset="calendar",
    schema=PROPOSE_EVENT_SCHEMA,
    handler=propose_handler,
    description=(
        "Stage calendar events into the consent-center for human confirmation "
        "(never writes the calendar directly)."
    ),
    emoji="\U0001f5d3️",
)
