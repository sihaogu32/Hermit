"""Tests for the read-only Google Calendar connector tool.

All tests mock credentials and the API client — they never hit the real Google
API and never require a real token. The credential layer is exercised by
patching the lazily-imported google libraries at their source module.
"""

import json
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from tools import google_calendar as gc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(items):
    """Return (fake_service, captured_kwargs) where events().list(**kw) records
    its kwargs into captured_kwargs and execute() yields {"items": items}."""
    captured = {}

    class _Request:
        def execute(self):
            return {"items": items}

    class _Events:
        def list(self, **kwargs):
            captured.update(kwargs)
            return _Request()

    class _Service:
        def events(self):
            return _Events()

    return _Service(), captured


_SAMPLE_TIMED = {
    "id": "evt-1",
    "summary": "Dentist appointment",
    "start": {"dateTime": "2026-06-02T09:00:00+08:00"},
    "end": {"dateTime": "2026-06-02T10:00:00+08:00"},
    "location": "Clinic A",
    "description": "Routine checkup",
    "status": "confirmed",
    "htmlLink": "https://calendar.google.com/evt-1",
}

_SAMPLE_ALLDAY = {
    "id": "evt-2",
    "summary": "Public holiday",
    "start": {"date": "2026-06-05"},
    "end": {"date": "2026-06-06"},
    "status": "confirmed",
    "htmlLink": "https://calendar.google.com/evt-2",
}


# ---------------------------------------------------------------------------
# needs_auth path
# ---------------------------------------------------------------------------


def test_needs_auth_when_token_missing(monkeypatch, tmp_path):
    """No token → needs_auth, and we never touch credentials or the API."""
    monkeypatch.setattr(gc, "_token_path", lambda: tmp_path / "google_token.json")
    no_creds = Mock(side_effect=AssertionError("must not load credentials"))
    no_build = Mock(side_effect=AssertionError("must not build the API client"))
    monkeypatch.setattr(gc, "_load_credentials", no_creds)
    monkeypatch.setattr(gc, "_build_service", no_build)

    result = gc.read_calendar_events()

    assert result["status"] == "needs_auth"
    assert "setup.py" in result["message"]
    no_creds.assert_not_called()
    no_build.assert_not_called()


def test_token_exists_check_fn(monkeypatch, tmp_path):
    token = tmp_path / "google_token.json"
    monkeypatch.setattr(gc, "_token_path", lambda: token)
    assert gc._token_exists() is False
    token.write_text("{}", encoding="utf-8")
    assert gc._token_exists() is True


# ---------------------------------------------------------------------------
# happy path: read + parse
# ---------------------------------------------------------------------------


def _arm_authorized(monkeypatch, tmp_path, items):
    """Make the token exist and inject a fake service returning ``items``."""
    token = tmp_path / "google_token.json"
    token.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gc, "_token_path", lambda: token)
    monkeypatch.setattr(gc, "_load_credentials", lambda: object())
    service, captured = _make_service(items)
    monkeypatch.setattr(gc, "_build_service", lambda creds: service)
    return captured


def test_reads_and_parses_events(monkeypatch, tmp_path):
    captured = _arm_authorized(monkeypatch, tmp_path, [_SAMPLE_TIMED, _SAMPLE_ALLDAY])

    result = gc.read_calendar_events(calendar_id="primary", days_ahead=7, max_results=10)

    assert result["status"] == "ok"
    assert result["calendar_id"] == "primary"
    assert result["event_count"] == 2

    first = result["events"][0]
    assert first["id"] == "evt-1"
    assert first["summary"] == "Dentist appointment"
    assert first["start"] == "2026-06-02T09:00:00+08:00"
    assert first["end"] == "2026-06-02T10:00:00+08:00"
    assert first["location"] == "Clinic A"
    assert first["description"] == "Routine checkup"
    assert first["status"] == "confirmed"
    assert first["html_link"] == "https://calendar.google.com/evt-1"
    assert first["all_day"] is False

    # All-day event: date-only start/end, all_day flag set.
    second = result["events"][1]
    assert second["start"] == "2026-06-05"
    assert second["all_day"] is True

    # Read-only, deterministic ordering, single-event expansion.
    assert captured["calendarId"] == "primary"
    assert captured["maxResults"] == 10
    assert captured["singleEvents"] is True
    assert captured["orderBy"] == "startTime"


def test_empty_calendar(monkeypatch, tmp_path):
    _arm_authorized(monkeypatch, tmp_path, [])
    result = gc.read_calendar_events()
    assert result["status"] == "ok"
    assert result["event_count"] == 0
    assert result["events"] == []


def test_missing_summary_defaults(monkeypatch, tmp_path):
    _arm_authorized(monkeypatch, tmp_path, [{"id": "x", "start": {}, "end": {}}])
    result = gc.read_calendar_events()
    assert result["events"][0]["summary"] == "(no title)"


def test_handler_returns_json_string(monkeypatch, tmp_path):
    _arm_authorized(monkeypatch, tmp_path, [_SAMPLE_TIMED])
    out = gc.handler({"calendar_id": "primary", "days_ahead": 7, "max_results": 5})
    assert isinstance(out, str)
    parsed = json.loads(out)
    assert parsed["status"] == "ok"
    assert parsed["event_count"] == 1


# ---------------------------------------------------------------------------
# time window
# ---------------------------------------------------------------------------


def test_days_ahead_window(monkeypatch, tmp_path):
    captured = _arm_authorized(monkeypatch, tmp_path, [])
    fixed = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(gc, "_now", lambda: fixed)

    gc.read_calendar_events(days_ahead=3)

    assert captured["timeMin"] == fixed.isoformat()
    t_min = datetime.fromisoformat(captured["timeMin"])
    t_max = datetime.fromisoformat(captured["timeMax"])
    assert (t_max - t_min).days == 3


# ---------------------------------------------------------------------------
# credential refresh + write-back
# ---------------------------------------------------------------------------


def test_expired_token_refreshes_and_writes_back(monkeypatch, tmp_path):
    token = tmp_path / "google_token.json"
    token.write_text(
        json.dumps({"scopes": ["https://www.googleapis.com/auth/calendar"],
                    "refresh_token": "rt"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(gc, "_token_path", lambda: token)

    class _FakeCreds:
        def __init__(self):
            self.expired = True
            self.refresh_token = "rt"
            self.refreshed = False

        def refresh(self, request):
            self.refreshed = True
            self.expired = False

        def to_json(self):
            return json.dumps({"token": "REFRESHED", "scopes": ["x"]})

    fake = _FakeCreds()
    with patch(
        "google.oauth2.credentials.Credentials.from_authorized_user_file",
        return_value=fake,
    ), patch("google.auth.transport.requests.Request"):
        creds = gc._load_credentials()

    assert creds is fake
    assert fake.refreshed is True
    # Refreshed token written back to disk.
    assert "REFRESHED" in token.read_text(encoding="utf-8")


def test_valid_token_not_rewritten(monkeypatch, tmp_path):
    token = tmp_path / "google_token.json"
    original = json.dumps({"scopes": ["https://www.googleapis.com/auth/calendar"],
                           "refresh_token": "rt", "token": "ORIGINAL"})
    token.write_text(original, encoding="utf-8")
    monkeypatch.setattr(gc, "_token_path", lambda: token)

    class _FakeCreds:
        expired = False
        refresh_token = "rt"

        def refresh(self, request):
            raise AssertionError("must not refresh a valid token")

        def to_json(self):
            raise AssertionError("must not rewrite a valid token")

    with patch(
        "google.oauth2.credentials.Credentials.from_authorized_user_file",
        return_value=_FakeCreds(),
    ):
        gc._load_credentials()

    assert token.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def test_registered_in_google_calendar_toolset():
    entry = gc.registry.get_entry("read_calendar_events")
    assert entry is not None
    assert entry.toolset == "google-calendar"
    # check_fn gates the tool on the token existing.
    assert entry.check_fn is gc._token_exists
