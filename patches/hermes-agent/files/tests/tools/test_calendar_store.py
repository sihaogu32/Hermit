"""Tests for the native calendar event store (tools/calendar_store.py).

All tests point HERMES_HOME at a tmp dir, so they never touch the real store.
"""

import json

import pytest

from tools import calendar_store as cs


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


def test_list_empty_when_no_file(home):
    assert cs.list_events() == []


def test_add_assigns_identity_and_defaults(home):
    stored = cs.add_event({"title": "Dentist", "start": "2026-06-02T09:00:00+08:00",
                           "end": "2026-06-02T10:00:00+08:00", "location": "Clinic A"})
    assert stored["id"]
    assert stored["created_at"]
    assert stored["updated_at"]
    assert stored["source"] == "native"      # default
    assert stored["status"] == "confirmed"    # default
    assert stored["all_day"] is False
    assert stored["title"] == "Dentist"


def test_add_then_list_roundtrip(home):
    cs.add_event({"title": "A", "start": "2026-06-02T09:00:00+08:00"})
    events = cs.list_events()
    assert len(events) == 1
    assert events[0]["title"] == "A"


def test_events_file_is_valid_json_with_schema_version(home):
    cs.add_event({"title": "A", "start": "2026-06-02T09:00:00+08:00"})
    path = tmp_events_path(home)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == cs.SCHEMA_VERSION
    assert isinstance(payload["events"], list) and len(payload["events"]) == 1


def test_list_sorted_by_start(home):
    cs.add_event({"title": "later", "start": "2026-06-05T09:00:00+00:00"})
    cs.add_event({"title": "earlier", "start": "2026-06-02T09:00:00+00:00"})
    titles = [e["title"] for e in cs.list_events()]
    assert titles == ["earlier", "later"]


def test_list_sort_is_instant_aware_across_timezones(home):
    # 02:00Z is earlier than 09:00+08:00 (= 01:00Z)? No: 09:00+08:00 == 01:00Z.
    cs.add_event({"title": "tokyo", "start": "2026-06-02T09:00:00+08:00"})   # 01:00Z
    cs.add_event({"title": "utc", "start": "2026-06-02T02:00:00+00:00"})     # 02:00Z
    titles = [e["title"] for e in cs.list_events()]
    assert titles == ["tokyo", "utc"]


def test_list_window_filters(home):
    cs.add_event({"title": "in", "start": "2026-06-10T09:00:00+00:00",
                  "end": "2026-06-10T10:00:00+00:00"})
    cs.add_event({"title": "before", "start": "2026-05-01T09:00:00+00:00",
                  "end": "2026-05-01T10:00:00+00:00"})
    cs.add_event({"title": "after", "start": "2026-07-01T09:00:00+00:00",
                  "end": "2026-07-01T10:00:00+00:00"})
    titles = [e["title"] for e in cs.list_events(
        start="2026-06-01T00:00:00+00:00", end="2026-06-30T23:59:59+00:00")]
    assert titles == ["in"]


def test_get_event(home):
    stored = cs.add_event({"title": "A", "start": "2026-06-02T09:00:00+00:00"})
    assert cs.get_event(stored["id"])["title"] == "A"
    assert cs.get_event("nope") is None


def test_update_merges_and_bumps_updated_at(home):
    stored = cs.add_event({"title": "A", "start": "2026-06-02T09:00:00+00:00"})
    updated = cs.update_event(stored["id"], {"title": "B", "location": "Home"})
    assert updated["title"] == "B"
    assert updated["location"] == "Home"
    assert updated["created_at"] == stored["created_at"]   # preserved
    assert updated["id"] == stored["id"]


def test_update_cannot_rewrite_source_or_provenance(home):
    stored = cs.add_event({"title": "A", "start": "2026-06-02T09:00:00+00:00"})
    updated = cs.update_event(stored["id"], {"source": "google", "id": "hacked",
                                             "source_ref": {"x": 1}})
    assert updated["source"] == "native"      # not overwritten
    assert updated["id"] == stored["id"]       # not overwritten
    assert updated["source_ref"] is None       # not overwritten


def test_update_missing_raises_keyerror(home):
    with pytest.raises(KeyError):
        cs.update_event("nope", {"title": "x"})


def test_delete(home):
    stored = cs.add_event({"title": "A", "start": "2026-06-02T09:00:00+00:00"})
    assert cs.delete_event(stored["id"]) is True
    assert cs.list_events() == []
    assert cs.delete_event("nope") is False


def test_title_defaults_when_blank(home):
    stored = cs.add_event({"start": "2026-06-02T09:00:00+00:00"})
    assert stored["title"] == "(no title)"


def test_end_defaults_to_start(home):
    stored = cs.add_event({"title": "A", "start": "2026-06-02T09:00:00+00:00"})
    assert stored["end"] == "2026-06-02T09:00:00+00:00"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def tmp_events_path(home):
    return home / "calendar" / "events.json"
