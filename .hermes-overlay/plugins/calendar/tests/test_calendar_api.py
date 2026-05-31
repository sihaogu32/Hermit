"""calendar plugin_api 端點整合測試（events CRUD + subscriptions CRUD）。

執行：
    cd ~/.hermes/hermes-agent
    venv/bin/python -m pytest ~/.hermes/plugins/calendar/tests/ -q -o 'addopts='

模式同 consent-center：tmp HERMES_HOME via monkeypatch.setenv、spec_from_file_location
重載 plugin_api、FastAPI + TestClient include_router prefix="/api/plugins/calendar"。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "dashboard"
PLUGIN_API = PLUGIN_DIR / "plugin_api.py"

# 本測試在 ~/.hermes/plugins/calendar/tests/ ；parents[3] = ~/.hermes
HERMES_AGENT = Path(__file__).resolve().parents[3] / "hermes-agent"

# 用一個寬視窗查詢，避免依賴「現在」落在 days_ahead 預設窗內。
WIDE = {"start": "2026-01-01T00:00:00+00:00", "end": "2027-01-01T00:00:00+00:00"}


def _ensure_sys_path() -> None:
    for p in (HERMES_AGENT, HERMES_AGENT / "tools"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)


_ensure_sys_path()


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes_home"
    (hermes_home / "calendar").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    return {"hermes_home": hermes_home}


@pytest.fixture
def api_module(tmp_env):
    _ensure_sys_path()
    sys.modules.pop("calendar_api", None)
    spec = importlib.util.spec_from_file_location("calendar_api", PLUGIN_API)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def client(api_module) -> TestClient:
    app = FastAPI()
    app.include_router(api_module.router, prefix="/api/plugins/calendar")
    return TestClient(app)


BASE = "/api/plugins/calendar"


# ──────────────── events ────────────────

def test_events_empty(client, tmp_env):
    r = client.get(f"{BASE}/events", params=WIDE)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["event_count"] == 0
    assert body["sources"]["native"] == 0


def test_event_crud_roundtrip(client, tmp_env):
    # create
    r = client.post(f"{BASE}/events", json={
        "title": "Dentist", "start": "2026-06-02T09:00:00+08:00",
        "end": "2026-06-02T10:00:00+08:00", "location": "Clinic A"})
    assert r.status_code == 200
    created = r.json()
    eid = created["id"]
    assert created["source"] == "native"
    assert created["title"] == "Dentist"

    # appears in merged view
    r = client.get(f"{BASE}/events", params=WIDE)
    events = r.json()["events"]
    assert len(events) == 1 and events[0]["id"] == eid

    # update
    r = client.patch(f"{BASE}/events/{eid}", json={"title": "Dentist (rescheduled)",
                                                   "location": "Clinic B"})
    assert r.status_code == 200
    assert r.json()["title"] == "Dentist (rescheduled)"
    assert r.json()["location"] == "Clinic B"

    # delete
    r = client.delete(f"{BASE}/events/{eid}")
    assert r.status_code == 200 and r.json()["deleted"] is True

    # gone
    r = client.get(f"{BASE}/events", params=WIDE)
    assert r.json()["event_count"] == 0


def test_update_missing_event_404(client, tmp_env):
    r = client.patch(f"{BASE}/events/nope", json={"title": "x"})
    assert r.status_code == 404


def test_delete_missing_event_404(client, tmp_env):
    r = client.delete(f"{BASE}/events/nope")
    assert r.status_code == 404


def test_window_filters_events(client, tmp_env):
    client.post(f"{BASE}/events", json={"title": "june", "start": "2026-06-15T09:00:00+00:00"})
    client.post(f"{BASE}/events", json={"title": "dec", "start": "2026-12-15T09:00:00+00:00"})
    r = client.get(f"{BASE}/events", params={
        "start": "2026-06-01T00:00:00+00:00", "end": "2026-06-30T00:00:00+00:00"})
    titles = [e["title"] for e in r.json()["events"]]
    assert titles == ["june"]


# ──────────────── subscriptions ────────────────

def test_subscriptions_empty(client, tmp_env):
    r = client.get(f"{BASE}/subscriptions")
    assert r.status_code == 200
    assert r.json() == {"subscriptions": []}


def test_subscription_crud_and_refresh_stub(client, tmp_env):
    # add
    r = client.post(f"{BASE}/subscriptions", json={
        "url": "https://calendar.google.com/calendar/ical/abc/private-xyz/basic.ics",
        "label": "我的 Google iCal"})
    assert r.status_code == 200
    sub = r.json()
    sid = sub["id"]
    assert sub["label"] == "我的 Google iCal"

    # list
    r = client.get(f"{BASE}/subscriptions")
    subs = r.json()["subscriptions"]
    assert len(subs) == 1 and subs[0]["id"] == sid

    # refresh → deferred stub (no icalendar yet)
    r = client.post(f"{BASE}/subscriptions/{sid}/refresh")
    assert r.status_code == 200
    assert r.json()["status"] == "deferred"

    # delete
    r = client.delete(f"{BASE}/subscriptions/{sid}")
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert client.get(f"{BASE}/subscriptions").json() == {"subscriptions": []}


def test_add_subscription_requires_url(client, tmp_env):
    r = client.post(f"{BASE}/subscriptions", json={"url": "  ", "label": "x"})
    assert r.status_code == 400


def test_delete_missing_subscription_404(client, tmp_env):
    r = client.delete(f"{BASE}/subscriptions/nope")
    assert r.status_code == 404
