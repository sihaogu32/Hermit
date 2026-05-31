"""Tests for the merged calendar read + propose tools (tools/calendar_read.py)."""

import json

import pytest

from tools import calendar_read as cr
from tools import calendar_store as cs


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


def _google(events):
    """Return a fetch_events stand-in yielding the given unified-schema events."""
    return lambda **kw: list(events)


def test_merges_native_and_google_sorted(home, monkeypatch):
    cs.add_event({"title": "native-late", "start": "2026-06-10T09:00:00+00:00"})
    monkeypatch.setattr(cr.google_calendar, "fetch_events", _google([
        {"id": "google:g1", "title": "google-early",
         "start": "2026-06-01T09:00:00+00:00", "end": "2026-06-01T10:00:00+00:00",
         "all_day": False, "source": "google", "source_ref": {}, "status": "confirmed"},
    ]))

    result = cr.read_calendar_events(days_ahead=30)
    assert result["status"] == "ok"
    assert result["event_count"] == 2
    assert result["sources"] == {"native": 1, "ics": 0, "google": 1}
    titles = [e["title"] for e in result["events"]]
    assert titles == ["google-early", "native-late"]      # sorted by start


def test_no_token_returns_native_only(home, monkeypatch):
    # Real adapter: no token -> fetch_events returns [].
    from datetime import datetime, timezone
    monkeypatch.setattr(cr, "_now", lambda: datetime(2026, 6, 1, tzinfo=timezone.utc))
    cs.add_event({"title": "native", "start": "2026-06-10T09:00:00+00:00"})
    result = cr.read_calendar_events(days_ahead=30)
    assert result["sources"]["google"] == 0
    assert [e["title"] for e in result["events"]] == ["native"]


def test_google_failure_degrades_to_native(home, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(cr, "_now", lambda: datetime(2026, 6, 1, tzinfo=timezone.utc))
    cs.add_event({"title": "native", "start": "2026-06-10T09:00:00+00:00"})

    def boom(**kw):
        raise RuntimeError("google down")

    monkeypatch.setattr(cr.google_calendar, "fetch_events", boom)
    result = cr.read_calendar_events(days_ahead=30)
    assert result["sources"]["google"] == 0
    assert result["event_count"] == 1     # native still present, no crash


def test_window_filters_native(home, monkeypatch):
    # Pin "now" so the window is deterministic.
    from datetime import datetime, timezone
    monkeypatch.setattr(cr, "_now", lambda: datetime(2026, 6, 1, tzinfo=timezone.utc))
    cs.add_event({"title": "soon", "start": "2026-06-03T09:00:00+00:00"})
    cs.add_event({"title": "far", "start": "2026-12-01T09:00:00+00:00"})
    result = cr.read_calendar_events(days_ahead=7)
    assert [e["title"] for e in result["events"]] == ["soon"]


def test_read_handler_returns_json_string(home, monkeypatch):
    monkeypatch.setattr(cr.google_calendar, "fetch_events", _google([]))
    out = cr.read_handler({"days_ahead": 7})
    assert isinstance(out, str)
    assert json.loads(out)["status"] == "ok"


def test_propose_handler_stages_event(home):
    out = cr.propose_handler({"items": [
        {"title": "Dentist", "start": "2026-06-02T09:00:00+08:00"}]})
    parsed = json.loads(out)
    assert parsed["item_count"] == 1
    # Staged, not written to the calendar.
    files = list((home / "consent_proposals").glob("*.json"))
    assert len(files) == 1
    assert cs.list_events() == []


def test_tools_registered_in_calendar_toolset():
    read = cr.registry.get_entry("read_calendar_events")
    propose = cr.registry.get_entry("propose_event")
    assert read is not None and read.toolset == "calendar"
    assert propose is not None and propose.toolset == "calendar"
