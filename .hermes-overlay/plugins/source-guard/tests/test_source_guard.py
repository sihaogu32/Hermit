"""source-guard plugin hook 測試（設計紅線#2 來源透明）。

移植自法務 citation-guard 的測試形狀。plugin __init__.py 只依賴 stdlib + urllib，
故以 spec_from_file_location 獨立載入即可（不需組裝 hermes core）。

涵蓋：
- transform_tool_result：harvest URL 進 grounded；排除 VerifySource 自我 echo；
  VerifySource not_found 強化 result、ok 不改；非字串 result 忽略。
- transform_llm_output：全引用已 grounded → None；未追溯連結 mode=block 攔截 +
  log；annotate 保留原文；off 不改但 log；同網域容忍路徑改寫；無 URL/非研究 →
  None；研究型零來源 → log-only advisory 不 mutate。
- 跨 session 隔離；on_session_end dump session_summary、無 state 不寫空 record。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PLUGIN_INIT = Path(__file__).resolve().parent.parent / "__init__.py"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("source_guard_under_test", PLUGIN_INIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sg = _load_plugin()


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    """每個 test：清空 per-session state、把 log 導到 tmp HERMES_HOME、清 mode 環境。"""
    sg._state.clear()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMIT_SOURCE_GUARD_MODE", raising=False)
    yield
    sg._state.clear()


def _read_log(tmp_path):
    files = list((tmp_path / "logs" / "source_violations").glob("*.jsonl"))
    if not files:
        return []
    return [
        json.loads(line)
        for line in files[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ──────────────── URL extraction ────────────────

def test_extract_strips_trailing_punctuation():
    urls = sg._extract_urls("見 https://example.com/a。另見 (https://example.com/b)，完。")
    assert "https://example.com/a" in urls
    assert "https://example.com/b" in urls


# ──────────────── transform_tool_result: grounding ────────────────

def test_tool_result_harvests_urls_into_grounded():
    sg._on_transform_tool_result(
        tool_name="web_search",
        result="results: https://nytimes.com/a and https://bbc.com/b",
        session_id="s1",
    )
    grounded = sg._peek("s1")["grounded"]
    assert "https://nytimes.com/a" in grounded
    assert "https://bbc.com/b" in grounded


def test_non_string_result_ignored():
    assert sg._on_transform_tool_result(tool_name="web_search", result=None, session_id="s1") is None
    assert sg._peek("s1")["grounded"] == set()


def test_verifysource_echo_not_grounded():
    # VerifySource 把 URL 原樣回 echo，不可被當成 grounded（否則替杜撰連結背書）
    result = json.dumps({"success": True, "status": "external", "ref": "https://made.up/x"})
    sg._on_transform_tool_result(tool_name="VerifySource", result=result, session_id="s1")
    assert "https://made.up/x" not in sg._peek("s1")["grounded"]


# ──────────────── transform_tool_result: VerifySource state ────────────────

def test_verifysource_not_found_reinforces_and_records():
    result = json.dumps({"success": True, "status": "not_found", "ref": "吃素"})
    out = sg._on_transform_tool_result(tool_name="VerifySource", result=result, session_id="s1")
    assert out is not None
    assert "status=not_found" in out
    assert sg._peek("s1")["verify"]["吃素"] == "not_found"


def test_verifysource_ok_does_not_reinforce():
    result = json.dumps({"success": True, "status": "ok", "ref": "早上開會"})
    out = sg._on_transform_tool_result(tool_name="VerifySource", result=result, session_id="s1")
    assert out is None
    assert sg._peek("s1")["verify"]["早上開會"] == "ok"


# ──────────────── transform_llm_output: grounded vs untraced ────────────────

def test_all_cited_urls_grounded_returns_none():
    sg._on_transform_tool_result(
        tool_name="web_extract", result="https://nytimes.com/story", session_id="s1"
    )
    out = sg._on_transform_llm_output(
        response_text="根據報導 https://nytimes.com/story 指出……", session_id="s1"
    )
    assert out is None


def test_untraced_url_blocks_by_default(tmp_path):
    out = sg._on_transform_llm_output(
        response_text="根據報導 https://fake.example/made-up 指出某事。", session_id="s1"
    )
    assert out is not None
    assert "已攔截" in out
    assert "https://fake.example/made-up" in out
    log = _read_log(tmp_path)
    assert any(
        r["type"] == "violation" and "https://fake.example/made-up" in r["untraced_urls"]
        for r in log
    )


def test_annotate_mode_preserves_original(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMIT_SOURCE_GUARD_MODE", "annotate")
    original = "詳見 https://made.up/x 的說明。"
    out = sg._on_transform_llm_output(response_text=original, session_id="s1")
    assert original in out
    assert "查證" in out
    assert _read_log(tmp_path)


def test_off_mode_logs_but_no_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMIT_SOURCE_GUARD_MODE", "off")
    out = sg._on_transform_llm_output(response_text="https://made.up/x", session_id="s1")
    assert out is None
    assert _read_log(tmp_path)


def test_host_level_grounding_tolerates_path():
    sg._on_transform_tool_result(
        tool_name="web_extract", result="https://example.com/page-a", session_id="s1"
    )
    out = sg._on_transform_llm_output(
        response_text="另見 https://example.com/page-b 一文。", session_id="s1"
    )
    assert out is None  # 同網域抓過 → 不攔


def test_plain_answer_no_urls_returns_none():
    out = sg._on_transform_llm_output(
        response_text="好的，我幫你把會議改到早上十點。", session_id="s1"
    )
    assert out is None


def test_research_no_source_is_log_only(tmp_path):
    text = (
        "根據最新研究，這套方法的成功率超過九成，多數使用者都回報明顯改善，"
        "相關報導也指出長期效果穩定可靠，後續調查顯示滿意度持續上升，值得參考。"
    )
    out = sg._on_transform_llm_output(response_text=text, session_id="s1")
    assert out is None  # advisory 不 mutate 回答
    log = _read_log(tmp_path)
    assert any(r.get("research_no_source") for r in log)


# ──────────────── per-session isolation ────────────────

def test_grounding_isolated_per_session():
    sg._on_transform_tool_result(
        tool_name="web_extract", result="https://example.com/a", session_id="sA"
    )
    # session sB 沒抓過 → 引用同一連結會被攔
    out = sg._on_transform_llm_output(
        response_text="見 https://example.com/a", session_id="sB"
    )
    assert out is not None
    assert "已攔截" in out


# ──────────────── on_session_end ────────────────

def test_session_end_dumps_summary(tmp_path):
    sg._on_transform_tool_result(
        tool_name="web_search", result="https://a.test/1 https://b.test/2", session_id="s1"
    )
    sg._on_transform_llm_output(response_text="見 https://made.up/x", session_id="s1")
    sg._on_session_end(session_id="s1", completed=True, interrupted=False)
    summaries = [r for r in _read_log(tmp_path) if r["type"] == "session_summary"]
    assert len(summaries) == 1
    s = summaries[0]
    assert s["grounded_sources"] == 2
    assert s["violations"] >= 1
    # drain 後 state 應清空
    assert sg._peek("s1")["grounded"] == set()


def test_session_end_no_state_writes_nothing(tmp_path):
    sg._on_session_end(session_id="ghost", completed=True, interrupted=False)
    assert _read_log(tmp_path) == []
