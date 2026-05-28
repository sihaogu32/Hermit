"""citation-guard plugin — 事中 / 事後 enforcement 設計紅線#2。

對應 spec §Enforcement 表第 2-4 列：

* ``transform_tool_result`` — 截 ``verify_citation`` 結果寫 per-session state；
  ``status != "ok"`` 時強化 result 訊息提示 model 下一輪務必修正。
* ``transform_llm_output`` — parse final response 中的法條引用；發現未驗證 /
  驗證失敗的引用 → mutate response + 寫 ``citation_violations/<YYYYMMDD>.jsonl``。
* ``on_session_end`` — dump 該 session 的驗證統計到同一 jsonl（``type="session_summary"``）。

對工具層完全唯讀，不重啟 hermes 就生效。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-session state
# ---------------------------------------------------------------------------

# key = task_id or session_id or "default"
# value = {(law_name, normalized_article_no): status}
_state: Dict[str, Dict[Tuple[str, str], str]] = {}
_lock = threading.Lock()


def _state_key(task_id: str, session_id: str) -> str:
    return task_id or session_id or "default"


def _record_verify(
    task_id: str,
    session_id: str,
    law_name: str,
    normalized_no: str,
    status: str,
) -> None:
    if not law_name or not normalized_no:
        return
    key = _state_key(task_id, session_id)
    with _lock:
        bucket = _state.setdefault(key, {})
        bucket[(law_name, normalized_no)] = status


def _drain_state(task_id: str, session_id: str) -> Dict[Tuple[str, str], str]:
    """Pop and return the verify-bucket for *task_id* / *session_id*."""
    key = _state_key(task_id, session_id)
    with _lock:
        return _state.pop(key, {})


def _peek_state(task_id: str, session_id: str) -> Dict[Tuple[str, str], str]:
    key = _state_key(task_id, session_id)
    with _lock:
        # Return a copy so callers can iterate without holding the lock.
        return dict(_state.get(key, {}))


# ---------------------------------------------------------------------------
# Article-no normalize（薄層；複用 tools/verify_citation._try_normalize 若可 import）
# ---------------------------------------------------------------------------


def _normalize_article(raw: str) -> str:
    """嘗試把 response 中抓到的條號標準化成 state 鍵格式。失敗回 ``""``。"""
    s = (raw or "").strip()
    if not s:
        return ""
    try:
        from tools.verify_citation import _try_normalize  # type: ignore
        return _try_normalize(f"第{s}條" if not s.startswith("第") else s)
    except Exception:
        # Fallback：手寫薄層接受裸阿拉伯（含 -）/ 「第 N 條」/ 「第 N-M 條」/
        # 「第N之M條」。中文數字 fallback 不在 plugin 範圍（complex；測試只覆 ASCII）。
        m = re.match(r"^(?:第\s*)?(\d+)(?:\s*[-之]\s*(\d+))?\s*條?$", s)
        if not m:
            return ""
        main_no, sub_no = m.group(1), m.group(2)
        return f"{main_no}-{sub_no}" if sub_no else main_no


# ---------------------------------------------------------------------------
# Citation regex（response 偵測用）
# ---------------------------------------------------------------------------

# 三型：
#   《公司法》第 8 條                  → 《》 包裹
#   公司法第 8 條                      → 直接相連
#   公司法 第 8 條                     → 中間有空白
# 條號允許：阿拉伯（含 -、之）；中文數字（一/二/三/.../十/百，可選「之N」）
_ART_NUMBER = (
    r"(\d+(?:[-之]\d+)?|"
    r"[〇零一二兩三四五六七八九十百]+(?:之[〇零一二兩三四五六七八九十百]+)?)"
)
# 兩型 pattern：
#   (a) 《...》 包裹（精確邊界）
#   (b) 中文連續串 + 「第 N 條」（依賴 _trim_law_prefix 後處理裁掉動詞前綴）
_LAW_NAME_BRACKET = r"([一-鿿]{2,15}?法(?:施行細則)?)"
_LAW_NAME_RUN = r"([一-鿿]+法(?:施行細則)?)"

_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"《" + _LAW_NAME_BRACKET + r"》\s*第\s*" + _ART_NUMBER + r"\s*條"),
    re.compile(_LAW_NAME_RUN + r"\s*第\s*" + _ART_NUMBER + r"\s*條"),
]


def _trim_law_prefix(raw: str) -> str:
    """裁掉常見動詞 / 介系詞前綴，回最右邊以「法」/「法施行細則」結尾的合理片段。

    策略：法名鮮少超過 8 個中文字（「金融控股公司法施行細則」11 字是極端），所以
    取末端的 2-11 字片段，剝掉常見前綴詞（「並參照」「另見」「依」「依據」「參照」
    「適用」「按」「準用」「準據」「參考」）。Pattern 不在這列就回原字串，由 state
    比對自己決定是否認得。
    """
    s = raw or ""
    if len(s) <= 4:
        return s
    prefixes = (
        "並參照", "另見", "依據", "參照", "適用", "準用", "參考",
        "依", "按", "見", "由",
    )
    for pre in prefixes:
        if s.startswith(pre) and len(s) - len(pre) >= 2:
            return s[len(pre):]
    return s


def _extract_citations(text: str) -> List[Tuple[str, str]]:
    """回傳 ``[(law_name, normalized_article_no), ...]``，去重保序。"""
    if not text:
        return []
    seen: set[Tuple[str, str]] = set()
    out: List[Tuple[str, str]] = []
    for pat in _PATTERNS:
        for m in pat.finditer(text):
            law_name = _trim_law_prefix(m.group(1))
            raw_no = m.group(2)
            normalized = _normalize_article(raw_no)
            if not normalized:
                continue
            key = (law_name, normalized)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


# ---------------------------------------------------------------------------
# Violation log
# ---------------------------------------------------------------------------


def _hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    # plugin 路徑為 .../.hermes/plugins/citation-guard/__init__.py
    return Path(__file__).resolve().parent.parent.parent


def _violation_log_path() -> Path:
    base = _hermes_home() / "logs" / "citation_violations"
    base.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return base / f"{today}.jsonl"


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")
    except Exception as exc:
        logger.warning("citation-guard append jsonl failed: %s", exc)


# ---------------------------------------------------------------------------
# Hook: transform_tool_result
# ---------------------------------------------------------------------------


_REINFORCE_TEMPLATE = (
    "[Citation guard] verify_citation 回傳 status={status}；"
    "務必使用下方 ground truth 修正引用、或改換法名 / 條號。"
    "在未取得 status=ok 之前不得引用該條。\n\n"
    "原 verify_citation 回傳：\n{original}"
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
    """記錄 verify_citation 結果；status 非 ok 時強化 result 訊息。"""
    if tool_name != "VerifyCitation" or not isinstance(result, str):
        return None
    try:
        payload = json.loads(result)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    status = payload.get("status", "")
    law_name = payload.get("law_name", "") or ""
    normalized_no = payload.get("normalized_article_no", "") or ""

    if law_name and normalized_no and status:
        _record_verify(task_id, session_id, law_name, normalized_no, status)

    if status == "ok" or not status:
        return None

    return _REINFORCE_TEMPLATE.format(status=status, original=result)


# ---------------------------------------------------------------------------
# Hook: transform_llm_output
# ---------------------------------------------------------------------------


_BLOCK_NOTICE_TEMPLATE = (
    "[Citation guard] 偵測到未驗證引用，原回答已攔截。\n"
    "未驗證 / 驗證失敗的引用：{violations}\n"
    "請依 SOUL.md 紀律先呼叫 verify_citation 工具驗證後再回答。"
)


def _on_transform_llm_output(
    response_text: str = "",
    session_id: str = "",
    model: str = "",
    platform: str = "",
    **_: Any,
) -> Optional[str]:
    """偵測 final response 中未驗證或驗證失敗的法條引用；違規則 mutate + log。"""
    citations = _extract_citations(response_text)
    if not citations:
        return None

    # transform_llm_output 沒有 task_id；以 session_id 為 key 對齊 state。
    verified = _peek_state("", session_id)

    violations: List[Dict[str, str]] = []
    for law_name, art_no in citations:
        status = verified.get((law_name, art_no))
        if status == "ok":
            continue
        violations.append(
            {
                "law_name": law_name,
                "article_no": art_no,
                "status": status or "unverified",
            }
        )

    if not violations:
        return None

    record = {
        "type": "violation",
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "model": model,
        "platform": platform,
        "violations": violations,
        "original_response": response_text,
    }
    _append_jsonl(_violation_log_path(), record)

    return _BLOCK_NOTICE_TEMPLATE.format(
        violations=", ".join(
            f"{v['law_name']}第{v['article_no']}條({v['status']})" for v in violations
        )
    )


# ---------------------------------------------------------------------------
# Hook: on_session_end
# ---------------------------------------------------------------------------


def _on_session_end(
    session_id: str = "",
    completed: bool = True,
    interrupted: bool = False,
    **_: Any,
) -> None:
    """Dump 該 session 的 verify 統計（ok 數 / 總呼叫數）到 violation jsonl。"""
    drained = _drain_state("", session_id)
    # 同時清掉同 process 內 task-scoped buckets（仿 disk-cleanup 模式）；
    # 若 task_id 非空會在自己的 bucket 結算，這裡只清 session_id-only。
    if not drained:
        return

    total = len(drained)
    ok = sum(1 for s in drained.values() if s == "ok")
    record = {
        "type": "session_summary",
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "completed": completed,
        "interrupted": interrupted,
        "verify_calls": total,
        "verify_ok": ok,
        "violation_rate": round(1 - (ok / total), 4) if total else 0.0,
    }
    _append_jsonl(_violation_log_path(), record)


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------


def register(ctx) -> None:
    ctx.register_hook("transform_tool_result", _on_transform_tool_result)
    ctx.register_hook("transform_llm_output", _on_transform_llm_output)
    ctx.register_hook("on_session_end", _on_session_end)
