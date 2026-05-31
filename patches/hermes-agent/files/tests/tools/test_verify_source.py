"""Tests for tools/verify_source.py — 來源可追溯性驗證（設計紅線#2）。

verify_source(memory) 對本地記憶庫（memories/*.md + managed/*.md）做標準化內容
比對，回 ok/not_found；verify_source(url) 回 external（離線不抓取）。
HERMES_HOME 全程指向 tmp dir。

Importing the module registers ``VerifySource`` into the global registry under
the ``source-guard`` toolset（agent 事前主動驗證入口；唯讀工具，非寫入路徑）。
"""

import json

import pytest

from tools import verify_source as vs
from tools.registry import registry


@pytest.fixture
def home(tmp_path, monkeypatch):
    mem = tmp_path / "memories"
    mem.mkdir()
    (mem / "MEMORY.md").write_text(
        "- 使用者偏好早上開會，不排晚於 18:00 的會議。\n"
        "- 慣用 Python 與 pytest。\n",
        encoding="utf-8",
    )
    (mem / "USER.md").write_text("使用者名叫司奧，住台北。\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


# ──────────────── memory: content match ────────────────

def test_memory_hit_returns_ok(home):
    r = vs.verify_source(ref="早上開會")
    assert r["status"] == "ok"
    assert r["source_kind"] == "memory"
    assert r["matched"] is True
    assert r["matched_in"] == "MEMORY.md"
    assert "早上開會" in r["matched_excerpt"]


def test_memory_match_ignores_punctuation_and_space(home):
    # 標準化比對：移空白/標點後 substring containment
    r = vs.verify_source(ref="不排晚於1800的會議")
    assert r["status"] == "ok"


def test_memory_miss_returns_not_found_with_candidates(home):
    r = vs.verify_source(ref="使用者最討厭一大早開會")
    assert r["status"] == "not_found"
    assert r["matched"] is False
    assert isinstance(r["candidates"], list)


def test_quoted_text_drives_match(home):
    # ref 是模糊關鍵字；提供 quoted_text 時以 quoted_text 內容比對
    r = vs.verify_source(ref="會議偏好", quoted_text="慣用 Python 與 pytest")
    assert r["status"] == "ok"


def test_quoted_text_mismatch_not_found(home):
    r = vs.verify_source(ref="會議偏好", quoted_text="喜歡半夜兩點開會")
    assert r["status"] == "not_found"


def test_managed_store_is_searched(home):
    managed = home / "memories" / "managed"
    managed.mkdir(parents=True)
    (managed / "CONFIRMED.md").write_text("- 已確認：使用者吃全素。\n", encoding="utf-8")
    r = vs.verify_source(ref="吃全素")
    assert r["status"] == "ok"
    assert r["matched_in"] == "CONFIRMED.md"


# ──────────────── url: external ────────────────

def test_url_kind_returns_external(home):
    r = vs.verify_source(ref="https://example.com/article")
    assert r["status"] == "external"
    assert r["source_kind"] == "url"
    assert "抓取" in r["usage_instruction"]


def test_auto_detect_url_without_source_kind(home):
    r = vs.verify_source(ref="http://foo.bar/x")
    assert r["source_kind"] == "url"


def test_explicit_memory_kind_overrides_url_looking_ref(home):
    r = vs.verify_source(ref="https://nope.example", source_kind="memory")
    assert r["source_kind"] == "memory"
    assert r["status"] == "not_found"


# ──────────────── edge / wiring ────────────────

def test_empty_ref_returns_empty(home):
    r = vs.verify_source(ref="")
    assert r["status"] == "empty"
    assert r["matched"] is False


def test_handler_wraps_success(home):
    payload = json.loads(vs._verify_source_handler({"ref": "早上開會"}))
    assert payload["success"] is True
    assert payload["status"] == "ok"


def test_registered_under_source_guard_toolset(home):
    entry = registry.get_entry("VerifySource")
    assert entry is not None
    assert entry.toolset == "source-guard"
    assert "VerifySource" in registry.get_tool_names_for_toolset("source-guard")


def test_dispatch_via_registry(home):
    out = registry.dispatch("VerifySource", {"ref": "https://x.test/y"})
    payload = json.loads(out)
    assert payload["success"] is True
    assert payload["status"] == "external"
