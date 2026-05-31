"""Native calendar event store for hermit (P1 calendar critical path).

The *only* writer into ``HERMES_HOME/calendar/events.json``. Holds the events
hermit owns: the ones a user adds/edits/deletes in the calendar dashboard, and
the ones the agent proposes that land here only after human confirmation via the
consent-center (see ``consent_event.apply_event``).

RED LINE alignment:
  - #3 (don't touch core): a plain ``tools/`` module; no hermes-agent core
    module is modified.
  - #5 (no silent writes to personal data): this module deliberately contains
    NO top-level ``registry.register(...)`` call and does not import the
    registry, so ``registry._module_registers_tools`` returns False for it and
    the agent can never invoke these functions directly. The agent reaches the
    store only by reading (via ``calendar_read``) or by proposing (via
    ``consent_event`` → human confirm). Dashboard edits are the user acting in
    person, which *is* the human confirmation.

External sources (ICS subscriptions, Google) are read-only mirrors handled
elsewhere; this store never holds them — only events with ``source="native"``.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from hermes_constants import get_hermes_home

SCHEMA_VERSION = 1

# Unified event fields (also the merged-view shape produced by calendar_read).
_EVENT_FIELDS = (
    "id",
    "title",
    "start",
    "end",
    "all_day",
    "location",
    "description",
    "source",
    "source_ref",
    "created_at",
    "updated_at",
    "status",
)


def _calendar_dir() -> Path:
    return get_hermes_home().expanduser().resolve() / "calendar"


def _events_path() -> Path:
    return _calendar_dir() / "events.json"


def _now_iso() -> str:
    """Current UTC time as ISO-8601. Indirected so tests can pin it."""
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value) -> datetime | None:
    """Best-effort parse of an event start/end into a UTC-aware datetime.

    Handles date-only ("2026-06-05"), naive datetimes (assumed UTC) and
    tz-aware datetimes. Returns ``None`` when unparseable so callers can decide
    whether to include the event rather than crash the whole read.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    # ``fromisoformat`` accepts trailing "Z" only from 3.11+, but be defensive.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_DT_MIN = datetime.min.replace(tzinfo=timezone.utc)


def _sort_key(event: dict) -> datetime:
    return _parse_iso(event.get("start")) or _DT_MIN


def _read_all() -> list[dict]:
    """Return all stored native events (empty list if the file is absent)."""
    path = _events_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    events = payload.get("events") if isinstance(payload, dict) else payload
    return list(events) if isinstance(events, list) else []


def _write_all(events: list[dict]) -> None:
    """Atomically persist the full event list (temp file + ``os.replace``)."""
    path = _events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, "events": events}
    tmp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _normalize(raw: dict) -> dict:
    """Coerce an incoming event dict into the unified schema with defaults."""
    event = {field: raw.get(field) for field in _EVENT_FIELDS}
    event["title"] = (raw.get("title") or "").strip() or "(no title)"
    event["start"] = raw.get("start") or ""
    event["end"] = raw.get("end") or event["start"]
    event["all_day"] = bool(raw.get("all_day", False))
    event["location"] = raw.get("location") or ""
    event["description"] = raw.get("description") or ""
    event["source"] = raw.get("source") or "native"
    event["source_ref"] = raw.get("source_ref")
    event["status"] = raw.get("status") or "confirmed"
    return event


def _in_window(event: dict, win_start: datetime | None, win_end: datetime | None) -> bool:
    if win_start is None and win_end is None:
        return True
    ev_start = _parse_iso(event.get("start"))
    ev_end = _parse_iso(event.get("end")) or ev_start
    # Unparseable times: include rather than silently drop a real event.
    if ev_start is None:
        return True
    if win_end is not None and ev_start > win_end:
        return False
    if win_start is not None and (ev_end or ev_start) < win_start:
        return False
    return True


def list_events(start: str | None = None, end: str | None = None) -> list[dict]:
    """Return native events sorted by start time, optionally windowed.

    ``start``/``end`` are ISO-8601 bounds; events whose [start, end] overlaps
    the window are returned. Both omitted → all events.
    """
    win_start = _parse_iso(start) if start else None
    win_end = _parse_iso(end) if end else None
    events = [e for e in _read_all() if _in_window(e, win_start, win_end)]
    events.sort(key=_sort_key)
    return events


def get_event(event_id: str) -> dict | None:
    for event in _read_all():
        if event.get("id") == event_id:
            return event
    return None


def add_event(event: dict) -> dict:
    """Add a native event. Assigns id/created_at/updated_at; returns the stored event."""
    stored = _normalize(event or {})
    now = _now_iso()
    stored["id"] = event.get("id") or uuid.uuid4().hex
    stored["created_at"] = event.get("created_at") or now
    stored["updated_at"] = now
    events = _read_all()
    events.append(stored)
    _write_all(events)
    return stored


def update_event(event_id: str, patch: dict) -> dict:
    """Merge ``patch`` into an existing event; bumps updated_at. Raises KeyError if absent."""
    events = _read_all()
    for idx, event in enumerate(events):
        if event.get("id") == event_id:
            merged = dict(event)
            # Only allow editing user-facing fields; never let a patch rewrite
            # identity/provenance/source.
            for key in ("title", "start", "end", "all_day", "location",
                        "description", "status"):
                if key in patch:
                    merged[key] = patch[key]
            merged = _normalize(merged)
            merged["id"] = event_id
            merged["created_at"] = event.get("created_at")
            merged["source"] = event.get("source") or "native"
            merged["source_ref"] = event.get("source_ref")
            merged["updated_at"] = _now_iso()
            events[idx] = merged
            _write_all(events)
            return merged
    raise KeyError(event_id)


def delete_event(event_id: str) -> bool:
    """Delete an event by id. Returns True if something was removed."""
    events = _read_all()
    remaining = [e for e in events if e.get("id") != event_id]
    if len(remaining) == len(events):
        return False
    _write_all(remaining)
    return True
