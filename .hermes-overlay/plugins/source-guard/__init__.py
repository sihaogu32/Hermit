"""source-guard plugin — 來源透明事中／事後 enforcement（設計紅線#2）。

移植自法務 citation-guard（docs/port-sources/citation-guard/）。把「權威來源＝
法規 KB」換成 hermit 的「答案依據＝web 連結／個人記憶」，沿用同一套 hook 架構：

* ``transform_tool_result`` — (1) 從**任何**工具結果蒐集出現過的 URL 進
  per-session「grounded」集合（agent 本回合實際看過的來源）；(2) 攔
  ``VerifySource`` 結果寫 verify state，``not_found`` 時強化提示 model 修正。
* ``transform_llm_output`` — 抽 final response 中被引用的 URL；任一既不在 grounded
  集合、其網域也沒出現過（= 本回合沒抓過，杜撰強訊號）→ 依 mode 處置並寫
  ``logs/source_violations/<YYYYMMDD>.jsonl``。研究型回答零來源另記 log-only
  advisory（過於模糊，不觸發攔截）。
* ``on_session_end`` — dump 該 session 來源統計到同檔（``type="session_summary"``）。

mode 由環境變數 ``HERMIT_SOURCE_GUARD_MODE`` 控制：
  * ``block``（預設）— 以攔截訊息**取代**原回答（對齊法務 citation-guard）。
  * ``annotate`` — 在原回答前加警示橫幅，保留原文。
  * ``off`` — 不改回答，只寫 audit log。

對工具層完全唯讀，不重啟 hermes 不改 core（紅線#3）。grounding 採網域層級比對，
刻意接受偽陰性（漏抓）大於偽陽性（誤攔好答案）——與 citation-guard 同哲學。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-session state（一律以 session_id 為鍵；不用 task_id，避免事中 hook 有 task_id
# 而事後 hook 只有 session_id 造成 bucket 對不上 → 誤判全部引用未追溯 → 誤攔）
# ---------------------------------------------------------------------------

# key = session_id or "default"
# value = {"grounded": set[str], "verify": dict[str, str], "violations": int}
_state: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def _key(session_id: str) -> str:
    return session_id or "default"


def _new_bucket() -> Dict[str, Any]:
    return {"grounded": set(), "verify": {}, "violations": 0}


def _peek(session_id: str) -> Dict[str, Any]:
    with _lock:
        b = _state.get(_key(session_id))
        if not b:
            return _new_bucket()
        return {
            "grounded": set(b["grounded"]),
            "verify": dict(b["verify"]),
            "violations": b["violations"],
        }


def _drain(session_id: str) -> Dict[str, Any]:
    with _lock:
        return _state.pop(_key(session_id), {})


# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------

_VALID_MODES = {"block", "annotate", "off"}


def _mode() -> str:
    m = (os.environ.get("HERMIT_SOURCE_GUARD_MODE") or "block").strip().lower()
    return m if m in _VALID_MODES else "block"


# ---------------------------------------------------------------------------
# URL extraction / normalize
# ---------------------------------------------------------------------------

# URL body 限 ASCII（RFC 3986 字集）——中文常緊接 URL 後無空白（例：".../a。另見"），
# 限 ASCII 可在第一個非 ASCII 字（如「。」「另」）斷開，不把後文吃進連結。
_URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#@!$&'()*+,;=%\[\]-]+", re.IGNORECASE)
# 連結尾端常被句讀 / markdown 收尾字元污染，剝掉
_URL_TRAILING = ".,;:!?'\")]}>。，、；：！？）」』】…*_"


def _normalize_url(raw: str) -> str:
    u = (raw or "").strip().rstrip(_URL_TRAILING)
    return u.rstrip("/")


def _url_host(u: str) -> str:
    try:
        return urlsplit(u).netloc.lower()
    except Exception:
        return ""


def _extract_urls(text: str) -> List[str]:
    """回傳去重保序的 normalized URL 清單。"""
    if not text:
        return []
    seen: Set[str] = set()
    out: List[str] = []
    for m in _URL_RE.finditer(text):
        u = _normalize_url(m.group(0))
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


# ---------------------------------------------------------------------------
# 研究型回答 / 記憶引用 heuristic（僅供 log-only advisory，門檻保守）
# ---------------------------------------------------------------------------

_RESEARCH_KEYWORDS = (
    "研究", "報導", "報告指出", "資料顯示", "據統計", "文獻", "新聞",
    "根據", "調查顯示",
    "research", "study", "according to", "evidence", "survey", "statistics",
    "reportedly",
)
_MEMORY_MARKERS = (
    "根據你的", "你的記憶", "你曾", "你提到過", "你說過", "你的偏好",
    "[memory:", "〔記憶", "依你先前",
)


def _looks_like_research(text: str) -> bool:
    # 中文資訊密度高，60 字已是有實質內容的研究型回答；門檻過高會漏記。
    if len(text or "") < 60:
        return False
    low = text.lower()
    return any(k in text or k in low for k in _RESEARCH_KEYWORDS)


def _has_memory_marker(text: str) -> bool:
    return any(k in (text or "") for k in _MEMORY_MARKERS)


# ---------------------------------------------------------------------------
# Violation log
# ---------------------------------------------------------------------------


def _hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    # plugin 路徑為 .../.hermes/plugins/source-guard/__init__.py
    return Path(__file__).resolve().parent.parent.parent


def _violation_log_path() -> Path:
    base = _hermes_home() / "logs" / "source_violations"
    base.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return base / f"{today}.jsonl"


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")
    except Exception as exc:
        logger.warning("source-guard append jsonl failed: %s", exc)


# ---------------------------------------------------------------------------
# Hook: transform_tool_result
# ---------------------------------------------------------------------------

_REINFORCE_TEMPLATE = (
    "[來源 guard] VerifySource 回傳 status={status}；該依據未在記憶庫找到。"
    "不要宣稱『你記得 / 你曾說過』；若屬新事實請走 propose_memory 提議後再引用。\n\n"
    "原 VerifySource 回傳：\n{original}"
)


def _on_transform_tool_result(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    result: Any = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    duration_ms: int = 0,
    **_: Any,
) -> Optional[str]:
    """蒐集任何工具結果中的 URL 進 grounded；攔 VerifySource 結果寫 verify state。"""
    if not isinstance(result, str) or not result:
        return None

    # (1) grounding：任何工具吐出的 URL 都算「本回合看過的來源」。
    # 例外：VerifySource 會把待驗證的 URL 原樣回 echo，harvest 它等於替杜撰連結
    # 自我背書，故排除自己。
    if tool_name != "VerifySource":
        urls = _extract_urls(result)
        if urls:
            with _lock:
                _state.setdefault(_key(session_id), _new_bucket())["grounded"].update(urls)

    # (2) VerifySource 結果
    if tool_name == "VerifySource":
        try:
            payload = json.loads(result)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        status = payload.get("status", "") or ""
        ref = payload.get("ref", "") or ""
        if ref and status:
            with _lock:
                _state.setdefault(_key(session_id), _new_bucket())["verify"][ref] = status
        if status == "not_found":
            return _REINFORCE_TEMPLATE.format(status=status, original=result)

    return None


# ---------------------------------------------------------------------------
# Hook: transform_llm_output
# ---------------------------------------------------------------------------

# 注意：此訊息會「直接顯示給使用者」（transform_llm_output 在 turn 收尾、tool loop
# 之外觸發一次，model 不會再讀到、也不會自動重答）。故文案對使用者講話，不對 model。
_BLOCK_TEMPLATE = (
    "⚠️ 來源 guard：這則回答引用了我這回合**沒有實際查證過**的連結，"
    "可能是記錯或杜撰的網址；為避免你採信不可靠來源，原回答已攔截、不予顯示。\n"
    "未經查證的連結：{urls}\n"
    "你可以要我「先實際抓取這些來源再回答」，或換個不需要外部連結的問法。"
)
_ANNOTATE_TEMPLATE = (
    "⚠️ [來源 guard] 以下連結本回合未實際抓取，請查證後再採信：\n{urls}\n\n{original}"
)


def _on_transform_llm_output(
    response_text: str = "",
    session_id: str = "",
    model: str = "",
    platform: str = "",
    **_: Any,
) -> Optional[str]:
    """偵測 final response 中未追溯的引用連結；違規則依 mode 處置 + log。"""
    cited = _extract_urls(response_text)
    bucket = _peek(session_id)
    grounded: Set[str] = bucket.get("grounded", set())
    grounded_hosts = {h for h in (_url_host(u) for u in grounded) if h}

    untraced: List[str] = []
    for u in cited:
        if u in grounded:
            continue
        host = _url_host(u)
        if host and host in grounded_hosts:
            continue  # 同網域抓過 → 視為可追溯（容忍路徑改寫，壓低誤攔）
        untraced.append(u)

    research_no_source = (
        not cited
        and _looks_like_research(response_text)
        and not _has_memory_marker(response_text)
    )

    if not untraced and not research_no_source:
        return None

    record = {
        "type": "violation",
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "model": model,
        "platform": platform,
        "untraced_urls": untraced,
        "research_no_source": research_no_source,
        "mode": _mode(),
        "original_response": response_text,
    }
    _append_jsonl(_violation_log_path(), record)
    with _lock:
        b = _state.setdefault(_key(session_id), _new_bucket())
        b["violations"] += len(untraced) + (1 if research_no_source else 0)

    # 只有「未追溯連結」這個精確訊號會 mutate 回答；research_no_source 純記錄。
    mode = _mode()
    if not untraced or mode == "off":
        return None

    urls_str = ", ".join(untraced)
    if mode == "annotate":
        return _ANNOTATE_TEMPLATE.format(urls=urls_str, original=response_text)
    return _BLOCK_TEMPLATE.format(urls=urls_str)


# ---------------------------------------------------------------------------
# Hook: on_session_end
# ---------------------------------------------------------------------------


def _on_session_end(
    session_id: str = "",
    completed: bool = True,
    interrupted: bool = False,
    **_: Any,
) -> None:
    """Dump 該 session 來源統計到 violation jsonl（type=session_summary）。"""
    drained = _drain(session_id)
    if not drained:
        return
    verify = drained.get("verify", {})
    record = {
        "type": "session_summary",
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "completed": completed,
        "interrupted": interrupted,
        "grounded_sources": len(drained.get("grounded", set())),
        "verify_calls": len(verify),
        "verify_not_found": sum(1 for s in verify.values() if s == "not_found"),
        "violations": drained.get("violations", 0),
    }
    _append_jsonl(_violation_log_path(), record)


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------


def register(ctx) -> None:
    ctx.register_hook("transform_tool_result", _on_transform_tool_result)
    ctx.register_hook("transform_llm_output", _on_transform_llm_output)
    ctx.register_hook("on_session_end", _on_session_end)
