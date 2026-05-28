"""legal-kb-admin plugin_api 端點整合測試。

執行：
    cd ~/.hermes/hermes-agent
    venv/bin/python -m pytest \\
        ~/.hermes/plugins/legal-kb-admin/tests/ \\
        -q -o 'addopts='

使用 tmp HERMES_HOME + monkey-patch get_hermes_home / get_legal_kb_dir，
不依賴實況 KB 與 hermes 真實 runtime。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "dashboard"
PLUGIN_API = PLUGIN_DIR / "plugin_api.py"


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    """準備 tmp HERMES_HOME（含 legal_kb_scans/）+ tmp KB（含 logs/change/）。"""
    hermes_home = tmp_path / "hermes_home"
    (hermes_home / "legal_kb_scans").mkdir(parents=True)

    kb = tmp_path / "wiki" / "legal" / "knowledge_base"
    kb.mkdir(parents=True)

    log_dir = kb.parent / "logs" / "change"
    log_dir.mkdir(parents=True)

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_LEGAL_KB_DIR", str(kb))

    return {
        "hermes_home": hermes_home,
        "scans_dir": hermes_home / "legal_kb_scans",
        "kb": kb,
        "log_dir": log_dir,
    }


@pytest.fixture
def api_module(tmp_env):
    """每個 test 都重新 load plugin_api（避免 module level cache 影響 monkey-patch）。"""
    hermes_agent = Path(__file__).resolve().parents[4] / "hermes-agent"
    if str(hermes_agent) not in sys.path:
        sys.path.insert(0, str(hermes_agent))

    # drop cached module if previous test loaded it
    sys.modules.pop("legal_kb_admin_api", None)
    spec = importlib.util.spec_from_file_location("legal_kb_admin_api", PLUGIN_API)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def client(api_module) -> TestClient:
    app = FastAPI()
    app.include_router(api_module.router, prefix="/api/plugins/legal-kb-admin")
    return TestClient(app)


def _write_scan(scans_dir: Path, scan_id: str, *, created_at: str = "2026-05-07T00:00:00+00:00",
                summary: dict | None = None, scan: dict | None = None) -> Path:
    payload = {
        "scan_id": scan_id,
        "created_at": created_at,
        "source_used": "moj-api",
        "raw_path": "/tmp/fake/ChLaw.json",
        "summary": summary or {"new": 1, "changed": 2, "obsolete": 0},
        "scan": scan or {
            "source_path": "/tmp/fake/ChLaw.json",
            "knowledge_base": "/tmp/kb",
            "keywords": ["銀行"],
            "counts": {"new": 1, "changed": 2, "obsolete": 0, "unchanged": 0},
            "new": ["銀行法"],
            "changed": ["保險法", "證券交易法"],
            "obsolete": [],
            "filtered_laws": {},
        },
    }
    path = scans_dir / f"{scan_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ──────────────── GET /scans ────────────────

def test_list_scans_empty(client, tmp_env):
    r = client.get("/api/plugins/legal-kb-admin/scans")
    assert r.status_code == 200
    assert r.json() == {"scans": []}


def test_list_scans_returns_sorted_desc(client, tmp_env):
    _write_scan(tmp_env["scans_dir"], "older0000001", created_at="2026-05-01T00:00:00+00:00")
    _write_scan(tmp_env["scans_dir"], "newer0000002", created_at="2026-05-07T00:00:00+00:00")
    r = client.get("/api/plugins/legal-kb-admin/scans")
    assert r.status_code == 200
    rows = r.json()["scans"]
    assert [row["scan_id"] for row in rows] == ["newer0000002", "older0000001"]
    assert rows[0]["summary"] == {"new": 1, "changed": 2, "obsolete": 0}
    assert rows[0]["source_used"] == "moj-api"


# ──────────────── GET /scans/{id} ────────────────

def test_get_scan_returns_full_payload(client, tmp_env):
    _write_scan(tmp_env["scans_dir"], "abcdef012345")
    r = client.get("/api/plugins/legal-kb-admin/scans/abcdef012345")
    assert r.status_code == 200
    body = r.json()
    assert body["scan_id"] == "abcdef012345"
    assert "scan" in body
    assert body["scan"]["new"] == ["銀行法"]


def test_get_scan_not_found(client, tmp_env):
    r = client.get("/api/plugins/legal-kb-admin/scans/nonexistent1")
    assert r.status_code == 404


# ──────────────── GET /history ────────────────

def test_list_history_empty(client, tmp_env):
    r = client.get("/api/plugins/legal-kb-admin/history")
    assert r.status_code == 200
    assert r.json() == {"history": []}


def test_list_history_returns_recent(client, tmp_env):
    log_dir = tmp_env["log_dir"]
    (log_dir / "extract_20260501_010101.json").write_text(
        json.dumps({"timestamp_utc": "20260501_010101", "counts": {"new": 1}}),
        encoding="utf-8",
    )
    (log_dir / "extract_20260507_010101.json").write_text(
        json.dumps({"timestamp_utc": "20260507_010101", "counts": {"new": 0, "changed": 3}}),
        encoding="utf-8",
    )
    r = client.get("/api/plugins/legal-kb-admin/history?limit=5")
    assert r.status_code == 200
    rows = r.json()["history"]
    assert len(rows) == 2
    # sorted reverse by filename
    assert rows[0]["filename"] == "extract_20260507_010101.json"
    assert rows[0]["counts"] == {"new": 0, "changed": 3}


# ──────────────── GET /history/{filename} ────────────────

def test_get_history_file(client, tmp_env):
    log_dir = tmp_env["log_dir"]
    payload = {"timestamp_utc": "20260507_010101", "counts": {"changed": 1}, "article_diffs": {}}
    (log_dir / "extract_20260507_010101.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )
    r = client.get("/api/plugins/legal-kb-admin/history/extract_20260507_010101.json")
    assert r.status_code == 200
    assert r.json() == payload


def test_get_history_not_found(client, tmp_env):
    r = client.get("/api/plugins/legal-kb-admin/history/extract_99999999_999999.json")
    assert r.status_code == 404


def test_get_history_invalid_filename(client, tmp_env):
    r = client.get("/api/plugins/legal-kb-admin/history/foo.json")
    assert r.status_code == 400


# ──────────────── POST /scans/{id}/confirm ────────────────

def test_confirm_invokes_run_apply_selected(client, tmp_env, api_module, monkeypatch):
    _write_scan(tmp_env["scans_dir"], "applyme00001")
    captured = {}

    def fake_apply(scan_id, *, laws=None, delete_obsolete=False):
        captured["scan_id"] = scan_id
        captured["laws"] = laws
        captured["delete_obsolete"] = delete_obsolete
        return {
            "applied": {"written": ["銀行法"], "deleted": [], "law_count": 1, "knowledge_base": "/tmp/kb"},
            "summaries": {"processed": ["銀行法"], "failed": {}, "index_count": 1, "knowledge_base": "/tmp/kb"},
            "changelog_path": "/tmp/kb/../logs/change/extract_20260507_010101.json",
        }

    monkeypatch.setattr(api_module._legal_kb, "run_apply_selected", fake_apply)

    r = client.post(
        "/api/plugins/legal-kb-admin/scans/applyme00001/confirm",
        json={"laws": ["銀行法"], "delete_obsolete": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["applied"]["written"] == ["銀行法"]
    assert body["changelog_path"].endswith(".json")
    assert captured == {"scan_id": "applyme00001", "laws": ["銀行法"], "delete_obsolete": True}


def test_confirm_returns_500_with_traceback_on_apply_failure(client, tmp_env, api_module, monkeypatch):
    _write_scan(tmp_env["scans_dir"], "failme000001")

    def boom(*args, **kwargs):
        raise RuntimeError("fake apply failure for test")

    monkeypatch.setattr(api_module._legal_kb, "run_apply_selected", boom)

    r = client.post(
        "/api/plugins/legal-kb-admin/scans/failme000001/confirm",
        json={},
    )
    assert r.status_code == 500
    assert "fake apply failure for test" in r.json()["detail"]
    # traceback present (multi-line)
    assert "RuntimeError" in r.json()["detail"]


def test_confirm_not_found(client, tmp_env, api_module, monkeypatch):
    # ensure run_apply_selected is never called
    def must_not_call(*args, **kwargs):
        raise AssertionError("run_apply_selected should not be called for 404 scan")

    monkeypatch.setattr(api_module._legal_kb, "run_apply_selected", must_not_call)

    r = client.post(
        "/api/plugins/legal-kb-admin/scans/missing00000/confirm",
        json={},
    )
    assert r.status_code == 404


# ──────────────── POST /scans/{id}/cancel ────────────────

def test_cancel_deletes_scan_file(client, tmp_env):
    path = _write_scan(tmp_env["scans_dir"], "cancelme0001")
    assert path.exists()
    r = client.post("/api/plugins/legal-kb-admin/scans/cancelme0001/cancel")
    assert r.status_code == 200
    assert r.json() == {"scan_id": "cancelme0001", "deleted": True}
    assert not path.exists()


def test_cancel_not_found(client, tmp_env):
    r = client.post("/api/plugins/legal-kb-admin/scans/missing00000/cancel")
    assert r.status_code == 404
