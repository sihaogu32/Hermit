"""Tests for the calendar-event consent applier (tools/consent_event.py).

propose_event only stages; apply_event is the gated writer that lands events in
the native store. HERMES_HOME points at a tmp dir throughout.
"""

import json

import pytest

from tools import consent_event as ce
from tools import calendar_store as cs


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


def _staged_payload(home):
    files = list((home / "consent_proposals").glob("*.json"))
    assert len(files) == 1
    return files[0], json.loads(files[0].read_text(encoding="utf-8"))


def test_propose_writes_staging_with_calendar_applier(home):
    res = ce.propose_event(
        [{"title": "Dentist", "start": "2026-06-02T09:00:00+08:00",
          "location": "Clinic A"}],
        source="agent",
    )
    assert res["item_count"] == 1
    path, payload = _staged_payload(home)
    assert payload["applier"] == ce.APPLIER == "calendar_event"
    assert payload["status"] == "pending"
    item = payload["items"][0]
    assert item["target"] == "calendar"
    assert item["id"]
    # content auto-built for the consent UI.
    assert "Dentist" in item["content"]
    assert "Clinic A" in item["content"]


def test_propose_does_not_touch_calendar_store(home):
    ce.propose_event([{"title": "X", "start": "2026-06-02T09:00:00+00:00"}])
    # No events.json should exist yet — staging only.
    assert cs.list_events() == []
    assert not (home / "calendar" / "events.json").exists()


def test_apply_writes_event_audit_and_unlinks(home):
    ce.propose_event([{"title": "Dentist", "start": "2026-06-02T09:00:00+08:00",
                       "end": "2026-06-02T10:00:00+08:00"}])
    path, payload = _staged_payload(home)
    proposal_id = payload["proposal_id"]

    result = ce.apply_event(proposal_id)

    # Event landed in the native store, source=native, with provenance.
    events = cs.list_events()
    assert len(events) == 1
    assert events[0]["title"] == "Dentist"
    assert events[0]["source"] == "native"
    assert events[0]["source_ref"]["proposal"] == proposal_id

    # Audit written to consent_history/, staging removed.
    assert result["count"] == 1
    audit_files = list((home / "consent_history").glob("confirm_*.json"))
    assert len(audit_files) == 1
    audit = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit["applier"] == "calendar_event"
    assert audit["counts"]["written"] == 1
    assert "events.json" in audit["target_path"]
    assert not path.exists()


def test_apply_only_selected_items(home):
    ce.propose_event([
        {"title": "A", "start": "2026-06-02T09:00:00+00:00", "id": "event-1"},
        {"title": "B", "start": "2026-06-03T09:00:00+00:00", "id": "event-2"},
    ])
    _, payload = _staged_payload(home)
    ce.apply_event(payload["proposal_id"], selected_item_ids=["event-1"])
    titles = [e["title"] for e in cs.list_events()]
    assert titles == ["A"]


def test_apply_missing_proposal_raises(home):
    with pytest.raises(FileNotFoundError):
        ce.apply_event("does-not-exist")


def test_module_registers_no_agent_tools(home):
    """RED LINE #5: neither propose_event nor apply_event is a registered tool;
    the module body must contain no top-level registry.register(...) call."""
    from pathlib import Path
    from tools import registry
    src = Path(ce.__file__)
    assert registry._module_registers_tools(src) is False
