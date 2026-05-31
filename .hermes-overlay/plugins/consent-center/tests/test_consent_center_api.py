"""consent-center plugin_api 端點整合測試 + apply_proposal 直測。

執行（下一階段才跑）：
    cd ~/.hermes/hermes-agent
    venv/bin/python -m pytest \\
        ~/.hermes/plugins/consent-center/tests/ \\
        -q -o 'addopts='

模式移植自 legal-kb-admin 的 test_legal_kb_admin_api.py：
tmp HERMES_HOME via monkeypatch.setenv、spec_from_file_location 重載 plugin_api、
FastAPI + TestClient include_router prefix="/api/plugins/consent-center"。

紅線守門（machine proposes / human confirms）：
- POST /confirm 對不存在 proposal 必須在「呼叫 apply_proposal 之前」就 404（case 7）。
- consent_memory 本身不是 agent tool；唯一 register 點是 consent_propose_tool（case 10）。
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

# 本測試在 /home/laura/.hermes/plugins/consent-center/tests/
# parents[3] = /home/laura/.hermes ；hermes-agent source 在其下
HERMES_AGENT = Path(__file__).resolve().parents[3] / "hermes-agent"


def _ensure_sys_path() -> None:
    """確保 hermes-agent 與其 tools 都在 sys.path，供 import tools.consent_memory。"""
    for p in (HERMES_AGENT, HERMES_AGENT / "tools"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)


_ensure_sys_path()


# ──────────────── fixtures ────────────────

@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    """準備 tmp HERMES_HOME，含 consent_proposals / consent_history / memories/managed。"""
    hermes_home = tmp_path / "hermes_home"
    proposals_dir = hermes_home / "consent_proposals"
    history_dir = hermes_home / "consent_history"
    managed_dir = hermes_home / "memories" / "managed"
    proposals_dir.mkdir(parents=True)
    history_dir.mkdir(parents=True)
    managed_dir.mkdir(parents=True)

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    return {
        "hermes_home": hermes_home,
        "proposals_dir": proposals_dir,
        "history_dir": history_dir,
        "managed_dir": managed_dir,
        "managed_path": managed_dir / "CONFIRMED.md",
    }


@pytest.fixture
def api_module(tmp_env):
    """每個 test 重新 load plugin_api（避免 module-level cache 干擾 monkeypatch）。"""
    _ensure_sys_path()
    sys.modules.pop("consent_center_api", None)
    spec = importlib.util.spec_from_file_location("consent_center_api", PLUGIN_API)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def client(api_module) -> TestClient:
    app = FastAPI()
    app.include_router(api_module.router, prefix="/api/plugins/consent-center")
    return TestClient(app)


# ──────────────── helpers ────────────────

def _proposal_payload(
    proposal_id: str,
    *,
    created_at: str = "2026-05-30T09:15:00+00:00",
    status: str = "pending",
    source: str = "google_calendar",
) -> dict:
    """依契約 F 構造一個含 2 items（item-1 target=user、item-2 target=memory）的 staging payload。"""
    return {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "created_at": created_at,
        "status": status,
        "source": source,
        "source_ref": {
            "connector": "google_calendar",
            "kind": "staging_fixture",
            "external_id": None,
        },
        "summary": {"item_count": 2, "targets": {"user": 1, "memory": 1}},
        "items": [
            {
                "id": "item-1",
                "target": "user",
                "kind": "preference",
                "content": "使用者每週二早上 9:00 固定有團隊 standup，排程時避開。",
                "selected_default": True,
                "source_ref": {"external_id": "evt_demo_001"},
            },
            {
                "id": "item-2",
                "target": "memory",
                "kind": "fact",
                "content": "使用者主要行事曆時區為 Asia/Taipei。",
                "selected_default": True,
                "source_ref": {"external_id": "evt_demo_002"},
            },
        ],
    }


def _write_proposal(
    proposals_dir: Path,
    proposal_id: str,
    *,
    created_at: str = "2026-05-30T09:15:00+00:00",
    status: str = "pending",
    source: str = "google_calendar",
) -> Path:
    payload = _proposal_payload(
        proposal_id, created_at=created_at, status=status, source=source
    )
    path = proposals_dir / f"{proposal_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_audit(history_dir: Path, filename: str, payload: dict) -> Path:
    path = history_dir / filename
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ──────────────── 1. GET /proposals 空 ────────────────

def test_list_proposals_empty(client, tmp_env):
    r = client.get("/api/plugins/consent-center/proposals")
    assert r.status_code == 200
    assert r.json() == {"proposals": []}


# ──────────────── 2. GET /proposals 兩筆倒序 + 欄位 ────────────────

def test_list_proposals_returns_sorted_desc_with_fields(client, tmp_env):
    _write_proposal(
        tmp_env["proposals_dir"], "20260501T000000Z-aaaaaaaa",
        created_at="2026-05-01T00:00:00+00:00",
    )
    _write_proposal(
        tmp_env["proposals_dir"], "20260530T091500Z-bbbbbbbb",
        created_at="2026-05-30T09:15:00+00:00",
    )
    r = client.get("/api/plugins/consent-center/proposals")
    assert r.status_code == 200
    rows = r.json()["proposals"]
    assert [row["proposal_id"] for row in rows] == [
        "20260530T091500Z-bbbbbbbb",
        "20260501T000000Z-aaaaaaaa",
    ]
    top = rows[0]
    # 精簡欄位齊全
    assert top["source"] == "google_calendar"
    assert top["status"] == "pending"
    assert "summary" in top
    assert top["created_at"] == "2026-05-30T09:15:00+00:00"


# ──────────────── 3. GET /proposals/{id} 完整 / 404 ────────────────

def test_get_proposal_returns_full_payload(client, tmp_env):
    _write_proposal(tmp_env["proposals_dir"], "20260530T091500Z-cccccccc")
    r = client.get(
        "/api/plugins/consent-center/proposals/20260530T091500Z-cccccccc"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["proposal_id"] == "20260530T091500Z-cccccccc"
    assert isinstance(body["items"], list) and len(body["items"]) == 2
    # item.source_ref 完整保留
    ids = {it["id"]: it for it in body["items"]}
    assert ids["item-1"]["target"] == "user"
    assert ids["item-1"]["source_ref"]["external_id"] == "evt_demo_001"
    assert ids["item-2"]["target"] == "memory"
    assert ids["item-2"]["source_ref"]["external_id"] == "evt_demo_002"


def test_get_proposal_not_found(client, tmp_env):
    r = client.get(
        "/api/plugins/consent-center/proposals/20260530T091500Z-nope0000"
    )
    assert r.status_code == 404


# ──────────────── 4. GET /history 空 / 倒序 ; /history/{filename} 正常/404/400 ────────────────

def test_list_history_empty(client, tmp_env):
    r = client.get("/api/plugins/consent-center/history")
    assert r.status_code == 200
    assert r.json() == {"history": []}


def test_list_history_returns_recent_desc(client, tmp_env):
    _write_audit(
        tmp_env["history_dir"],
        "confirm_20260501T000000Z-aaaaaaaa_20260501T000001Z.json",
        {"written_at": "2026-05-01T00:00:01+00:00", "counts": {"written": 1}},
    )
    _write_audit(
        tmp_env["history_dir"],
        "confirm_20260530T091500Z-bbbbbbbb_20260530T091501Z.json",
        {"written_at": "2026-05-30T09:15:01+00:00", "counts": {"written": 2}},
    )
    r = client.get("/api/plugins/consent-center/history?limit=5")
    assert r.status_code == 200
    rows = r.json()["history"]
    assert len(rows) == 2
    # 倒序（最新的在前）；每筆回 filename / written_at / counts
    assert rows[0]["filename"] == "confirm_20260530T091500Z-bbbbbbbb_20260530T091501Z.json"
    assert rows[0]["written_at"] == "2026-05-30T09:15:01+00:00"
    assert rows[0]["counts"] == {"written": 2}


def test_get_history_file(client, tmp_env):
    filename = "confirm_20260530T091500Z-bbbbbbbb_20260530T091501Z.json"
    payload = {
        "proposal_id": "20260530T091500Z-bbbbbbbb",
        "source": "google_calendar",
        "selected_item_ids": ["item-1"],
        "written": [{"id": "item-1", "target": "user", "content": "x"}],
        "written_at": "2026-05-30T09:15:01+00:00",
        "target_path": "/tmp/managed/CONFIRMED.md",
        "counts": {"written": 1},
    }
    _write_audit(tmp_env["history_dir"], filename, payload)
    r = client.get(f"/api/plugins/consent-center/history/{filename}")
    assert r.status_code == 200
    assert r.json() == payload


def test_get_history_not_found(client, tmp_env):
    r = client.get(
        "/api/plugins/consent-center/history/confirm_20260101T000000Z-deadbeef_20260101T000001Z.json"
    )
    assert r.status_code == 404


def test_get_history_invalid_prefix(client, tmp_env):
    # 非 confirm_ 前綴 → 400（即使檔案不存在也要先被前綴守門擋下）
    r = client.get("/api/plugins/consent-center/history/notconfirm_foo.json")
    assert r.status_code == 400


# ──────────────── 5. POST /confirm 走 apply_proposal（fake） ────────────────

def test_confirm_invokes_apply_proposal(client, tmp_env, api_module, monkeypatch):
    _write_proposal(tmp_env["proposals_dir"], "20260530T091500Z-applyme0")
    captured = {}

    def fake_apply(proposal_id, selected_item_ids=None):
        captured["proposal_id"] = proposal_id
        captured["selected_item_ids"] = selected_item_ids
        return {
            "proposal_id": proposal_id,
            "written": ["item-1"],
            "audit_path": "/tmp/hermes/consent_history/confirm_x_y.json",
            "count": 1,
        }

    monkeypatch.setattr(api_module.consent_memory, "apply_proposal", fake_apply)

    r = client.post(
        "/api/plugins/consent-center/proposals/20260530T091500Z-applyme0/confirm",
        json={"selected_item_ids": ["item-1"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["written"] == ["item-1"]
    assert body["audit_path"].endswith(".json")
    assert captured["proposal_id"] == "20260530T091500Z-applyme0"
    assert captured["selected_item_ids"] == ["item-1"]


# ──────────────── 6. POST /confirm apply 失敗 → 500 + traceback ────────────────

def test_confirm_returns_500_with_traceback_on_apply_failure(
    client, tmp_env, api_module, monkeypatch
):
    _write_proposal(tmp_env["proposals_dir"], "20260530T091500Z-failme00")

    def boom(*args, **kwargs):
        raise RuntimeError("fake apply failure for test")

    monkeypatch.setattr(api_module.consent_memory, "apply_proposal", boom)

    r = client.post(
        "/api/plugins/consent-center/proposals/20260530T091500Z-failme00/confirm",
        json={},
    )
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "fake apply failure for test" in detail
    assert "RuntimeError" in detail  # traceback present


# ──────────────── 7. 【紅線守門】不存在 proposal → 404 且 apply 絕不被呼叫 ────────────────

def test_confirm_not_found_never_calls_apply(client, tmp_env, api_module, monkeypatch):
    def must_not_call(*args, **kwargs):
        raise AssertionError("apply_proposal must not be called for a missing proposal")

    monkeypatch.setattr(api_module.consent_memory, "apply_proposal", must_not_call)

    r = client.post(
        "/api/plugins/consent-center/proposals/20260530T091500Z-missing0/confirm",
        json={"selected_item_ids": ["item-1"]},
    )
    assert r.status_code == 404


# ──────────────── 8. POST /cancel 刪檔 / 404 ────────────────

def test_cancel_deletes_proposal_file(client, tmp_env):
    path = _write_proposal(tmp_env["proposals_dir"], "20260530T091500Z-cancel00")
    assert path.exists()
    r = client.post(
        "/api/plugins/consent-center/proposals/20260530T091500Z-cancel00/cancel"
    )
    assert r.status_code == 200
    assert r.json() == {"proposal_id": "20260530T091500Z-cancel00", "deleted": True}
    assert not path.exists()


def test_cancel_not_found(client, tmp_env):
    r = client.post(
        "/api/plugins/consent-center/proposals/20260530T091500Z-missing0/cancel"
    )
    assert r.status_code == 404


# ──────────────── 9. apply_proposal 直測（真跑、不 mock） ────────────────

def test_apply_proposal_writes_only_selected(tmp_env):
    """tmp HERMES_HOME 放 staging json → apply_proposal 只寫 item-1。

    斷言：
    - 只有 item-1 內容寫進 _managed_path()，item-2 未寫
    - audit json 生成於 consent_history/ 且檔名 confirm_ 前綴
    - staging 檔被 unlink
    """
    _ensure_sys_path()
    sys.modules.pop("tools.consent_memory", None)
    import tools.consent_memory as consent_memory

    proposal_id = "20260530T091500Z-direct00"
    staging_path = _write_proposal(tmp_env["proposals_dir"], proposal_id)
    assert staging_path.exists()

    result = consent_memory.apply_proposal(proposal_id, selected_item_ids=["item-1"])

    # 受管 store 只寫了 item-1
    managed_path = tmp_env["managed_path"]
    assert managed_path.exists()
    managed_text = managed_path.read_text(encoding="utf-8")
    assert "使用者每週二早上 9:00 固定有團隊 standup" in managed_text  # item-1
    assert "使用者主要行事曆時區為 Asia/Taipei" not in managed_text     # item-2 未寫

    # 回傳形狀
    assert result["proposal_id"] == proposal_id
    assert result["written"] == ["item-1"]
    assert result["count"] == 1
    assert result["audit_path"].endswith(".json")

    # audit json 落在 consent_history/，confirm_ 前綴
    audit_path = Path(result["audit_path"])
    assert audit_path.exists()
    assert audit_path.parent == tmp_env["history_dir"]
    assert audit_path.name.startswith("confirm_")
    assert audit_path.name.endswith(".json")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["selected_item_ids"] == ["item-1"]
    assert audit["counts"]["written"] == 1
    assert [w["id"] for w in audit["written"]] == ["item-1"]

    # staging 檔已被 unlink
    assert not staging_path.exists()


def test_apply_proposal_missing_raises(tmp_env):
    """不存在的 proposal → FileNotFoundError。"""
    _ensure_sys_path()
    sys.modules.pop("tools.consent_memory", None)
    import tools.consent_memory as consent_memory

    with pytest.raises(FileNotFoundError):
        consent_memory.apply_proposal("20260530T091500Z-ghost000")


# ──────────────── 10. 【紅線回歸】只有 propose tool 是 register 點 ────────────────

def test_registry_register_points(tmp_env):
    """consent_memory 不是 agent tool；consent_propose_tool 是唯一 register 點。"""
    _ensure_sys_path()
    sys.modules.pop("tools.consent_memory", None)
    import tools.consent_memory as consent_memory
    from tools import registry

    consent_memory_path = Path(consent_memory.__file__)
    propose_tool_path = HERMES_AGENT / "tools" / "consent_propose_tool.py"

    assert registry._module_registers_tools(consent_memory_path) is False
    assert registry._module_registers_tools(propose_tool_path) is True


# ──────────────── 11. applier 分派：calendar_event → calendar_store ────────────────

def _write_calendar_proposal(proposals_dir: Path, proposal_id: str) -> Path:
    """構造一個 applier=calendar_event 的 staging proposal（含 1 個事件 item）。"""
    payload = {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "created_at": "2026-05-31T09:00:00+00:00",
        "status": "pending",
        "applier": "calendar_event",
        "source": "agent",
        "source_ref": None,
        "summary": {"item_count": 1, "targets": {"calendar": 1}},
        "items": [
            {
                "id": "event-1",
                "target": "calendar",
                "title": "Dentist",
                "start": "2026-06-02T09:00:00+08:00",
                "end": "2026-06-02T10:00:00+08:00",
                "content": "2026-06-02T09:00:00+08:00 Dentist",
            }
        ],
    }
    path = proposals_dir / f"{proposal_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_confirm_calendar_event_routes_to_calendar_store(
    client, tmp_env, api_module, monkeypatch
):
    """applier=calendar_event 的 proposal confirm → 落 calendar/events.json
    （非 CONFIRMED.md），且 memory applier 絕不被呼叫。"""

    def must_not_call(*args, **kwargs):
        raise AssertionError("memory applier must not be called for a calendar_event proposal")

    monkeypatch.setattr(api_module.consent_memory, "apply_proposal", must_not_call)

    path = _write_calendar_proposal(tmp_env["proposals_dir"], "20260531T090000Z-calendar")
    r = client.post(
        "/api/plugins/consent-center/proposals/20260531T090000Z-calendar/confirm",
        json={},
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1

    # 事件落 calendar/events.json（source=native），CONFIRMED.md 未被寫。
    events_path = tmp_env["hermes_home"] / "calendar" / "events.json"
    assert events_path.exists()
    events = json.loads(events_path.read_text(encoding="utf-8"))["events"]
    assert len(events) == 1
    assert events[0]["title"] == "Dentist"
    assert events[0]["source"] == "native"
    assert not tmp_env["managed_path"].exists()

    # audit 落 consent_history/，staging 被 unlink。
    audits = list(tmp_env["history_dir"].glob("confirm_*.json"))
    assert len(audits) == 1
    assert not path.exists()
