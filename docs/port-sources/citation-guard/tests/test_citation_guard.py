"""citation-guard plugin 單元測試。

檔名 ``test_citation_guard`` 取識別性，避免 pytest basename 撞名（CLAUDE.md 警示）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


HERMES_AGENT_ROOT = (
    Path(__file__).resolve().parents[4] / "hermes-agent"
)
PLUGIN_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate_state_and_logs(monkeypatch, tmp_path):
    """每個 test 換一個 HERMES_HOME 並清空 plugin per-session state。"""
    fake_home = tmp_path / "hermes_home"
    fake_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(fake_home))

    # 引入 hermes-agent 路徑，使 plugin 內 ``from tools.verify_citation import ...``
    # 在純測試 context（無 hermes runtime）下也能命中真實 _try_normalize。
    if str(HERMES_AGENT_ROOT) not in sys.path:
        sys.path.insert(0, str(HERMES_AGENT_ROOT))

    mod = _load_plugin_module()
    with mod._lock:
        mod._state.clear()
    yield mod
    with mod._lock:
        mod._state.clear()


def _load_plugin_module():
    """Load citation-guard ``__init__.py`` as a standalone module for tests."""
    name = "citation_guard_under_test"
    init_file = PLUGIN_DIR / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        name, init_file, submodule_search_locations=[str(PLUGIN_DIR)]
    )
    assert spec and spec.loader
    if name in sys.modules:
        return sys.modules[name]
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# transform_tool_result
# ---------------------------------------------------------------------------


def test_transform_tool_result_status_ok_records_state_and_returns_none(
    _isolate_state_and_logs,
):
    mod = _isolate_state_and_logs
    payload = {
        "status": "ok",
        "law_name": "公司法",
        "normalized_article_no": "8",
        "article_content": "...",
    }
    out = mod._on_transform_tool_result(
        tool_name="VerifyCitation",
        args={},
        result=json.dumps(payload),
        task_id="t-A",
        session_id="s-1",
    )
    assert out is None
    state = mod._peek_state("t-A", "s-1")
    assert state[("公司法", "8")] == "ok"


def test_transform_tool_result_content_mismatch_reinforces_message(
    _isolate_state_and_logs,
):
    mod = _isolate_state_and_logs
    payload = {
        "status": "content_mismatch",
        "law_name": "金融控股公司法",
        "normalized_article_no": "95-1",
        "article_content": "GROUND-TRUTH-ARTICLE",
    }
    raw_result = json.dumps(payload, ensure_ascii=False)
    out = mod._on_transform_tool_result(
        tool_name="VerifyCitation",
        args={},
        result=raw_result,
        task_id="t-A",
        session_id="s-1",
    )
    assert isinstance(out, str)
    assert "Citation guard" in out
    assert "content_mismatch" in out
    assert "GROUND-TRUTH-ARTICLE" in out
    state = mod._peek_state("t-A", "s-1")
    assert state[("金融控股公司法", "95-1")] == "content_mismatch"


def test_transform_tool_result_ignores_unrelated_tools(_isolate_state_and_logs):
    mod = _isolate_state_and_logs
    out = mod._on_transform_tool_result(
        tool_name="GetLawArticle",
        args={},
        result='{"status": "ok"}',
        task_id="t-A",
        session_id="s-1",
    )
    assert out is None
    assert mod._peek_state("t-A", "s-1") == {}


# ---------------------------------------------------------------------------
# Citation regex（三型 + normalize）
# ---------------------------------------------------------------------------


def test_extract_citations_three_forms(_isolate_state_and_logs):
    mod = _isolate_state_and_logs
    text = (
        "依《公司法》第 8 條規定，"
        "並參照金融控股公司法第95-1條，"
        "另見銀行法 第 25 條。"
    )
    cites = mod._extract_citations(text)
    assert ("公司法", "8") in cites
    assert ("金融控股公司法", "95-1") in cites
    assert ("銀行法", "25") in cites


def test_extract_citations_normalize_dash_form(_isolate_state_and_logs):
    mod = _isolate_state_and_logs
    cites = mod._extract_citations("公司法第 95-1 條")
    assert cites == [("公司法", "95-1")]


# ---------------------------------------------------------------------------
# transform_llm_output
# ---------------------------------------------------------------------------


def _has_violation_record(home: Path) -> bool:
    base = home / "logs" / "citation_violations"
    if not base.exists():
        return False
    for f in base.glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("type") == "violation":
                return True
    return False


def test_transform_llm_output_all_verified_returns_none(_isolate_state_and_logs):
    mod = _isolate_state_and_logs
    # Seed state with a verified citation
    mod._record_verify("", "s-final", "公司法", "8", "ok")
    response = "依《公司法》第 8 條，董事會應..."
    out = mod._on_transform_llm_output(response_text=response, session_id="s-final")
    assert out is None


def test_transform_llm_output_unverified_mutates_and_logs(
    _isolate_state_and_logs, tmp_path
):
    mod = _isolate_state_and_logs
    response = "依公司法第 9 條規定，..."
    out = mod._on_transform_llm_output(response_text=response, session_id="s-final")
    assert isinstance(out, str)
    assert "Citation guard" in out
    assert "公司法第9條" in out
    home = Path(os.environ["HERMES_HOME"])
    assert _has_violation_record(home)


def test_transform_llm_output_failed_status_mutates(_isolate_state_and_logs):
    mod = _isolate_state_and_logs
    mod._record_verify("", "s-final", "公司法", "8", "content_mismatch")
    response = "公司法第 8 條規定..."
    out = mod._on_transform_llm_output(response_text=response, session_id="s-final")
    assert isinstance(out, str)
    assert "content_mismatch" in out


def test_transform_llm_output_no_citation_returns_none(_isolate_state_and_logs):
    mod = _isolate_state_and_logs
    out = mod._on_transform_llm_output(
        response_text="這段文字沒有任何法條引用。",
        session_id="s-empty",
    )
    assert out is None


# ---------------------------------------------------------------------------
# Per-session 隔離
# ---------------------------------------------------------------------------


def test_per_task_state_isolation(_isolate_state_and_logs):
    mod = _isolate_state_and_logs
    mod._record_verify("t-A", "", "公司法", "8", "ok")
    mod._record_verify("t-B", "", "公司法", "9", "ok")
    a = mod._peek_state("t-A", "")
    b = mod._peek_state("t-B", "")
    assert a == {("公司法", "8"): "ok"}
    assert b == {("公司法", "9"): "ok"}


# ---------------------------------------------------------------------------
# on_session_end
# ---------------------------------------------------------------------------


def _read_session_summaries(home: Path):
    out = []
    base = home / "logs" / "citation_violations"
    if not base.exists():
        return out
    for f in base.glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("type") == "session_summary":
                out.append(rec)
    return out


def test_on_session_end_dumps_summary_jsonl(_isolate_state_and_logs):
    mod = _isolate_state_and_logs
    sid = "s-end"
    mod._record_verify("", sid, "公司法", "8", "ok")
    mod._record_verify("", sid, "公司法", "9", "content_mismatch")
    mod._record_verify("", sid, "銀行法", "25", "ok")

    mod._on_session_end(session_id=sid, completed=True, interrupted=False)

    summaries = _read_session_summaries(Path(os.environ["HERMES_HOME"]))
    assert len(summaries) == 1
    rec = summaries[0]
    assert rec["session_id"] == sid
    assert rec["verify_calls"] == 3
    assert rec["verify_ok"] == 2
    assert rec["violation_rate"] == round(1 - 2 / 3, 4)


def test_on_session_end_no_state_no_record(_isolate_state_and_logs):
    mod = _isolate_state_and_logs
    mod._on_session_end(session_id="s-noop")
    assert _read_session_summaries(Path(os.environ["HERMES_HOME"])) == []
