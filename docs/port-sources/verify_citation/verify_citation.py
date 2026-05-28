#!/usr/bin/env python3
"""verify_citation — 設計紅線#2 落地工具（MVP）。

對應 spec：docs/citation-verification.md。複用 tools/legal_kb.py 的
KB 路徑解析、條號 normalize 與條索引建立 helper；不重寫、不 refactor。
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any

from tools.legal_kb import (
    _build_article_index,
    _normalize_article_no,
    get_legal_kb_dir,
    read_index,
)
from tools.registry import registry


# ---------------------------------------------------------------------------
# 中文數字 → ASCII 薄層（範圍 1-999 + 附條；超出範圍 raise，由 caller 收成 article_not_found）
# ---------------------------------------------------------------------------

_CN_DIGITS: dict[str, int] = {
    "零": 0, "〇": 0,
    "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}

_CN_FALLBACK_RE = re.compile(
    r"^第\s*([〇零一二兩三四五六七八九十百0-9]+)\s*條"
    r"(?:\s*之\s*([〇零一二兩三四五六七八九十百0-9]+))?\s*$"
)


def _cn_segment_to_int(seg: str) -> int:
    """將中文數字片段轉阿拉伯整數（僅支援 1-999）；超出範圍 raise ValueError。"""
    if seg.isdigit():
        return int(seg)
    if any(ch in seg for ch in ("千", "萬", "億")):
        raise ValueError(f"out-of-range chinese numeral: {seg!r}")
    total = 0
    current = 0
    for ch in seg:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
        elif ch == "十":
            total += (current if current else 1) * 10
            current = 0
        elif ch == "百":
            total += (current if current else 1) * 100
            current = 0
        else:
            raise ValueError(f"unsupported chinese numeral char: {ch!r}")
    total += current
    if total <= 0 or total > 999:
        raise ValueError(f"out-of-range chinese numeral: {seg!r}")
    return total


def _try_normalize(raw: str) -> str:
    """先試既有 helper（裸條號 / 「第 95-1 條」）；失敗 fallback 中文數字（「第八條」/「第九十五條之一」）。"""
    s = (raw or "").strip()
    if not s:
        raise ValueError("article number is empty")
    try:
        return _normalize_article_no(s)
    except ValueError:
        pass
    m = _CN_FALLBACK_RE.match(s)
    if not m:
        raise ValueError(f"cannot parse article number: {raw!r}")
    main_part, sub_part = m.group(1), m.group(2)
    main_int = int(main_part) if main_part.isdigit() else _cn_segment_to_int(main_part)
    if sub_part is None:
        return str(main_int)
    sub_int = int(sub_part) if sub_part.isdigit() else _cn_segment_to_int(sub_part)
    return f"{main_int}-{sub_int}"


# ---------------------------------------------------------------------------
# 內容比對：移空白 + 移常見中英標點，再做 substring containment
# ---------------------------------------------------------------------------

_PUNCT_CHARS = "，。、；：？！「」『』（）〈〉《》()\"',.;:?!\\-—–·…"
_PUNCT_RE = re.compile(f"[{re.escape(_PUNCT_CHARS)}]")


def _strip_for_compare(text: str) -> str:
    text = re.sub(r"\s+", "", text or "")
    return _PUNCT_RE.sub("", text)


# ---------------------------------------------------------------------------
# 引用 format 塑形（L2.a：citation_block / usage_instruction / warning）
# ---------------------------------------------------------------------------

_USAGE_OK_WITH_QUOTED = (
    "引用本條時必須以 citation_block 開頭、article_content 內容（或其節錄）"
    "緊接其後；不得改寫法名與條號。"
)
_USAGE_OK_WITHOUT_QUOTED = (
    "已驗證法名與條號存在；引用時請以 citation_block 開頭、article_content"
    "（或其節錄）緊接其後。建議下次補 quoted_text 進行內容驗證。"
)
_USAGE_LAW_NOT_FOUND = (
    "本法名未在 KB 中。可參考 candidates 欄位的模糊匹配候選；"
    "確認正確法名後重新呼叫 verify_citation。在取得 status=ok 前不得引用此法。"
)
_USAGE_ARTICLE_NOT_FOUND = (
    "此條號於該法不存在。建議呼叫 GetLawToc 工具取得該法完整條號清單後重試。"
    "在取得 status=ok 前不得引用此條。"
)
_USAGE_CONTENT_MISMATCH = (
    "您草擬的引文與 ground-truth 不符；必須改用回傳的 article_content 原文"
    "（不得改寫），或重新草擬 quoted_text 後再驗證。"
)
_WARNING_NO_QUOTED_TEXT = (
    "未提供 quoted_text，無法擔保引用內容；"
    "建議先草擬引用文字後再呼叫驗證以提高保證等級。"
)


def _format_citation_block(law_name: str, normalized_article_no: str) -> str:
    """產出『《法名》第 N 條』中文書名號 format。"""
    return f"《{law_name}》第 {normalized_article_no} 條"


# ---------------------------------------------------------------------------
# 主 handler
# ---------------------------------------------------------------------------


def verify_citation(
    law_name: str,
    article_no: str,
    quoted_text: str | None = None,
    kb_dir: str | None = None,
) -> dict[str, Any]:
    """驗證法條引用（紅線#2）；回傳 dict 鍵見 spec §回傳 schema。

    KB index.json 內鍵名為小寫 ``law_name``；spec 文字寫的 ``LawName``
    是 source ChLaw.json 概念欄，落地時 fuzzy 對小寫 ``law_name``。
    """
    base = get_legal_kb_dir(kb_dir)
    safe_name = (law_name or "").strip()

    try:
        normalized = _try_normalize(article_no)
    except ValueError:
        normalized = ""

    if not safe_name:
        return {
            "status": "law_not_found",
            "normalized_article_no": normalized,
            "law_name": law_name or "",
            "article_content": "",
            "law_modified_date": "",
            "candidates": [],
            "usage_instruction": _USAGE_LAW_NOT_FOUND,
        }

    detail_path = base / safe_name / f"{safe_name}.json"
    if not detail_path.exists():
        candidates: list[str] = []
        try:
            idx = read_index(str(base))
            names = [
                row.get("law_name", "")
                for row in idx
                if isinstance(row, dict) and row.get("law_name")
            ]
            candidates = difflib.get_close_matches(safe_name, names, n=3, cutoff=0.4)
        except Exception:
            pass
        return {
            "status": "law_not_found",
            "normalized_article_no": normalized,
            "law_name": safe_name,
            "article_content": "",
            "law_modified_date": "",
            "candidates": candidates,
            "usage_instruction": _USAGE_LAW_NOT_FOUND,
        }

    with detail_path.open("r", encoding="utf-8") as f:
        detail = json.load(f)
    actual_law_name = detail.get("LawName") or safe_name
    law_modified_date = detail.get("LawModifiedDate", "")
    article_idx = _build_article_index(detail.get("LawArticles", []) or [])

    if not normalized or normalized not in article_idx:
        payload: dict[str, Any] = {
            "status": "article_not_found",
            "normalized_article_no": normalized,
            "law_name": actual_law_name,
            "article_content": "",
            "law_modified_date": law_modified_date,
            "usage_instruction": _USAGE_ARTICLE_NOT_FOUND,
        }
        if normalized:
            payload["citation_block"] = _format_citation_block(actual_law_name, normalized)
        return payload

    article = article_idx[normalized]
    article_content = article.get("ArticleContent", "")

    payload = {
        "status": "ok",
        "normalized_article_no": normalized,
        "law_name": actual_law_name,
        "article_content": article_content,
        "law_modified_date": law_modified_date,
        "citation_block": _format_citation_block(actual_law_name, normalized),
    }
    if quoted_text is None:
        payload["usage_instruction"] = _USAGE_OK_WITHOUT_QUOTED
        payload["warning"] = _WARNING_NO_QUOTED_TEXT
        return payload

    q_norm = _strip_for_compare(quoted_text)
    a_norm = _strip_for_compare(article_content)
    matched = bool(q_norm) and q_norm in a_norm
    payload["match_detail"] = {
        "matched": matched,
        "method": "normalized_substring",
        "normalized_query_excerpt": q_norm[:120],
        "normalized_article_excerpt": a_norm[:120],
    }
    if matched:
        payload["usage_instruction"] = _USAGE_OK_WITH_QUOTED
    else:
        payload["status"] = "content_mismatch"
        payload["usage_instruction"] = _USAGE_CONTENT_MISMATCH
    return payload


# ---------------------------------------------------------------------------
# Toolset registration（仿 tools/legal_kb.py:914-945 的 RunDownloadAndScan 模式）
# ---------------------------------------------------------------------------


def _verify_citation_available() -> bool:
    base = get_legal_kb_dir()
    return base.exists()


def _verify_citation_handler(args: Any, **kwargs: Any) -> str:
    args = args if isinstance(args, dict) else {}
    try:
        result = verify_citation(
            law_name=args.get("law_name", ""),
            article_no=args.get("article_no", ""),
            quoted_text=args.get("quoted_text"),
            kb_dir=args.get("kb_dir"),
        )
        return json.dumps({"success": True, **result}, ensure_ascii=False, indent=2)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2)


registry.register(
    name="VerifyCitation",
    toolset="legal_kb",
    schema={
        "name": "VerifyCitation",
        "description": (
            "驗證法條引用：檢查 (法名, 條號) 是否存在於本地 KB；若提供 quoted_text "
            "還會做標準化內容比對。回傳的 citation_block + article_content 是必須在最終"
            "答案中使用的引用格式：以 citation_block 字串開頭、article_content（或其節錄）"
            "緊接其後，不得改寫法名與條號。"
            "任一狀態都回 ground-truth ArticleContent 給 agent 自我修正。"
            "狀態：ok / law_not_found / article_not_found / content_mismatch。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "law_name": {
                    "type": "string",
                    "description": "法規名稱，如 '公司法' / '金融控股公司法'",
                },
                "article_no": {
                    "type": "string",
                    "description": "條號，可接受 '8' / '95-1' / '第 95-1 條' / '第八條' / '第九十五條之一'",
                },
                "quoted_text": {
                    "type": "string",
                    "description": (
                        "agent 計畫引述的條文文字。建議務必提供以啟動內容驗證；"
                        "不提供時驗證等級為『法名/條號 only』，回傳會帶 warning 欄位提醒。"
                    ),
                },
                "kb_dir": {"type": "string"},
            },
            "required": ["law_name", "article_no"],
        },
    },
    handler=_verify_citation_handler,
    check_fn=_verify_citation_available,
    description="法條引用驗證（設計紅線#2）",
    emoji="🔎",
)
