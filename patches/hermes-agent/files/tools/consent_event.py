"""Consent applier for agent-proposed calendar events (machine proposes / human confirms).

Parallel to ``consent_memory`` but for calendar events. The agent never writes
the calendar directly: it stages a proposal via ``propose_event`` (exposed as an
agent tool by ``calendar_read``), and the event lands in the native store only
after a human confirms it through the consent-center.

Routing: ``propose_event`` writes a staging proposal whose top-level
``"applier"`` is ``"calendar_event"``. The consent-center confirm endpoint reads
that field and dispatches here (``apply_event``) instead of the default memory
applier — so calendar events flow through the SAME single consent inbox/UI but
land in ``calendar/events.json`` rather than the memory store.

RED LINE alignment:
  - #5: this module deliberately contains NO top-level ``registry.register(...)``
    call. ``propose_event`` only stages (never writes the calendar); ``apply_event``
    is the gated writer and is reachable only from the confirm endpoint, never as
    an agent tool. ``calendar_store`` remains the sole writer of ``events.json``.
  - #3: a plain ``tools/`` module; no hermes-agent core is touched.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from hermes_constants import get_hermes_home
from tools import calendar_store

APPLIER = "calendar_event"

_TS_FMT = "%Y%m%dT%H%M%SZ"


def _proposals_dir() -> Path:
    return get_hermes_home().expanduser().resolve() / "consent_proposals"


def _history_dir() -> Path:
    return get_hermes_home().expanduser().resolve() / "consent_history"


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime(_TS_FMT)


def _build_content(item: dict) -> str:
    """Human-readable one-liner shown in the consent-center UI."""
    title = (item.get("title") or "(no title)").strip()
    start = (item.get("start") or "").strip()
    location = (item.get("location") or "").strip()
    parts = [p for p in (start, title) if p]
    line = " ".join(parts) if parts else title
    if location:
        line = f"{line} @ {location}"
    return line


def propose_event(items, source="agent", source_ref=None) -> dict:
    """Stage candidate calendar events for human confirmation.

    Writes ONLY to the staging area; never touches the calendar store. Each item
    is an event candidate carrying structured fields (title/start/end/all_day/
    location/description) that ``apply_event`` will write on confirm.
    """
    items = items or []
    normalized = []
    for idx, raw in enumerate(items, start=1):
        item = dict(raw)
        item.setdefault("id", f"event-{idx}")
        item["target"] = "calendar"
        if not item.get("content"):
            item["content"] = _build_content(item)
        normalized.append(item)

    proposal_id = f"{_utc_ts()}-{uuid.uuid4().hex[:8]}"
    created_at = datetime.now(timezone.utc).isoformat()

    payload = {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "created_at": created_at,
        "status": "pending",
        "applier": APPLIER,
        "source": source,
        "source_ref": source_ref,
        "summary": {"item_count": len(normalized), "targets": {"calendar": len(normalized)}},
        "items": normalized,
    }

    proposals_dir = _proposals_dir()
    proposals_dir.mkdir(parents=True, exist_ok=True)
    path = proposals_dir / f"{proposal_id}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "proposal_id": proposal_id,
        "path": str(path),
        "item_count": len(normalized),
    }


def apply_event(proposal_id, selected_item_ids=None) -> dict:
    """Apply a staged calendar-event proposal into the native store. Confirm-only.

    Reads the staging file, writes the selected events into ``calendar_store``
    (source="native", with provenance in source_ref), records an audit entry in
    ``consent_history/`` (same shape as the memory applier so the history panel
    renders both uniformly), then unlinks the staging file.
    """
    proposal_path = _proposals_dir() / f"{proposal_id}.json"
    if not proposal_path.exists():
        raise FileNotFoundError(proposal_id)

    payload = json.loads(proposal_path.read_text(encoding="utf-8"))
    source = payload.get("source")
    items = payload.get("items", [])

    if selected_item_ids is None:
        selected = list(items)
    else:
        selected_set = set(selected_item_ids)
        selected = [it for it in items if it.get("id") in selected_set]

    iso = datetime.now(timezone.utc).isoformat()

    written = []
    for item in selected:
        item_id = item.get("id")
        stored = calendar_store.add_event({
            "title": item.get("title") or item.get("content") or "(no title)",
            "start": item.get("start"),
            "end": item.get("end"),
            "all_day": bool(item.get("all_day", False)),
            "location": item.get("location") or "",
            "description": item.get("description") or "",
            "source": "native",
            "source_ref": {
                "proposal": proposal_id,
                "item": item_id,
                "origin": source,
                "ref": item.get("source_ref") or payload.get("source_ref"),
            },
        })
        written.append({"id": item_id, "event_id": stored["id"],
                        "content": item.get("content", "")})

    ts = _utc_ts()
    history_dir = _history_dir()
    history_dir.mkdir(parents=True, exist_ok=True)
    audit_path = history_dir / f"confirm_{proposal_id}_{ts}.json"
    audit_payload = {
        "proposal_id": proposal_id,
        "applier": APPLIER,
        "source": source,
        "selected_item_ids": [w["id"] for w in written],
        "written": written,
        "written_at": iso,
        "target_path": str(calendar_store._events_path()),
        "counts": {"written": len(written)},
    }
    audit_path.write_text(
        json.dumps(audit_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    proposal_path.unlink()

    return {
        "proposal_id": proposal_id,
        "written": [w["event_id"] for w in written],
        "audit_path": str(audit_path),
        "count": len(written),
    }
