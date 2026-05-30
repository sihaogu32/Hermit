"""Consent-center managed-store helpers (machine proposes / human confirms).

Pure-function module for the hermit "consent-center" plugin. It stages
connector-derived candidate memories into a review area and, on explicit
human confirmation (via the plugin's POST /confirm endpoint), appends them to a
self-managed store.

RED LINE #5: the *only* writer into personal memory is ``apply_proposal``, and
``apply_proposal`` is never exposed as an agent tool. This module body
deliberately contains NO top-level ``registry.register(...)`` call and does not
import the registry, so ``registry._module_registers_tools`` returns False for
it and the agent can never invoke these functions directly.

RED LINE #3: we do not touch hermes core nor the stock memory stores
(MEMORY.md / USER.md). Everything lands under our own managed paths.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from hermes_constants import get_hermes_home

_TS_FMT = "%Y%m%dT%H%M%SZ"


def _proposals_dir() -> Path:
    return get_hermes_home().expanduser().resolve() / "consent_proposals"


def _history_dir() -> Path:
    return get_hermes_home().expanduser().resolve() / "consent_history"


def _managed_path() -> Path:
    return (
        get_hermes_home().expanduser().resolve()
        / "memories"
        / "managed"
        / "CONFIRMED.md"
    )


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime(_TS_FMT)


def propose_memory(items, source="google_calendar", source_ref=None) -> dict:
    """Stage candidate memories for human confirmation.

    Writes ONLY to the staging area; never touches any memory store.
    """
    items = items or []
    normalized = []
    targets = {}
    for idx, raw in enumerate(items, start=1):
        item = dict(raw)
        item.setdefault("id", f"item-{idx}")
        item.setdefault("target", "memory")
        target = item.get("target", "memory")
        targets[target] = targets.get(target, 0) + 1
        normalized.append(item)

    proposal_id = f"{_utc_ts()}-{uuid.uuid4().hex[:8]}"
    created_at = datetime.now(timezone.utc).isoformat()

    payload = {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "created_at": created_at,
        "status": "pending",
        "source": source,
        "source_ref": source_ref,
        "summary": {"item_count": len(normalized), "targets": targets},
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


def apply_proposal(proposal_id, selected_item_ids=None) -> dict:
    """Apply a staged proposal into the managed store. Confirm-endpoint only.

    This is the sole writer into the managed memory store. Reads the staging
    file, appends the selected items to the managed path, writes an audit
    record, then unlinks the staging file.
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

    managed_path = _managed_path()
    managed_path.parent.mkdir(parents=True, exist_ok=True)

    written = []
    with managed_path.open("a", encoding="utf-8") as fh:
        for item in selected:
            item_id = item.get("id")
            target = item.get("target", "memory")
            content = item.get("content", "")
            fh.write(
                f"- [{target}] {content}  "
                f"(source={source}, item={item_id}, "
                f"proposal={proposal_id}, at={iso})\n"
            )
            written.append({"id": item_id, "target": target, "content": content})

    ts = _utc_ts()
    history_dir = _history_dir()
    history_dir.mkdir(parents=True, exist_ok=True)
    audit_path = history_dir / f"confirm_{proposal_id}_{ts}.json"
    audit_payload = {
        "proposal_id": proposal_id,
        "source": source,
        "selected_item_ids": [w["id"] for w in written],
        "written": written,
        "written_at": iso,
        "target_path": str(managed_path),
        "counts": {"written": len(written)},
    }
    audit_path.write_text(
        json.dumps(audit_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    proposal_path.unlink()

    return {
        "proposal_id": proposal_id,
        "written": [w["id"] for w in written],
        "audit_path": str(audit_path),
        "count": len(written),
    }
