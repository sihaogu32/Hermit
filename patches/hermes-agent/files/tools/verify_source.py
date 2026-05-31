#!/usr/bin/env python3
"""verify_source — 來源透明 guard 的驗證工具（設計紅線#2，MVP）。

移植自法務 `docs/port-sources/verify_citation/`，把「權威來源＝法規 KB」換成
hermit 的「答案依據＝個人記憶／外部連結」：

* ``source_kind="memory"``（個人化回答可追溯）：對本地記憶庫
  （``memories/MEMORY.md``、``memories/USER.md``、``memories/managed/*.md``）做
  標準化內容比對，回 ``ok`` / ``not_found`` + 命中節錄。這是 verify_citation
  「(law_name, article_no) 內容比對」在個人資料上的對應。
* ``source_kind="url"``（研究型回答附引用）：URL 屬外部來源，本工具**不做線上
  抓取**（離線不可驗證、且抓取屬另一條路徑）。回 ``external`` 並提示：只引用本
  回合實際 web_extract / browser 抓取過的連結——該 grounding 由 source-guard
  plugin 的 ``transform_tool_result`` 蒐集、``transform_llm_output`` 事後兜底。

不動 hermes-agent core（紅線#3）：純新增 tool，鏡像到 patches/hermes-agent/files/。
toolset ``source-guard`` 預設不在 platform_toolsets 啟用；hook 強制不依賴此工具，
此工具是 agent「事前主動驗證」的入口（對應 verify_citation 在法務的角色）。
"""

from __future__ import annotations

import difflib
import json
import os
import re
from pathlib import Path
from typing import Any

from tools.registry import registry


# ---------------------------------------------------------------------------
# 來源種類判定
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _detect_kind(ref: str) -> str:
    return "url" if _URL_RE.match(ref or "") else "memory"


# ---------------------------------------------------------------------------
# 內容比對：移空白 + 移常見中英標點，再做 substring containment
# （與 verify_citation._strip_for_compare 同策略，避免標點/空白造成假性不符）
# ---------------------------------------------------------------------------

_PUNCT_CHARS = "，。、；：？！「」『』（）〈〉《》()\"',.;:?!\\-—–·…"
_PUNCT_RE = re.compile(f"[{re.escape(_PUNCT_CHARS)}]")


def _strip_for_compare(text: str) -> str:
    text = re.sub(r"\s+", "", text or "")
    return _PUNCT_RE.sub("", text)


# ---------------------------------------------------------------------------
# 記憶庫檔案探索
# ---------------------------------------------------------------------------


def _hermes_home(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    return Path.home() / ".hermes"


def _memory_files(home: Path) -> list[Path]:
    """回傳存在的記憶庫檔案（核心 MEMORY/USER + consent 受管 store）。"""
    base = home / "memories"
    files: list[Path] = []
    for name in ("MEMORY.md", "USER.md"):
        p = base / name
        if p.exists():
            files.append(p)
    managed = base / "managed"
    if managed.is_dir():
        files.extend(sorted(managed.glob("*.md")))
    return files


def _matching_excerpt(content: str, normalized_query: str) -> str:
    """回傳含命中片段的原始行（去頭尾空白），找不到回空。"""
    for line in content.splitlines():
        if normalized_query and normalized_query in _strip_for_compare(line):
            return line.strip()
    return ""


# ---------------------------------------------------------------------------
# usage_instruction 文案
# ---------------------------------------------------------------------------

_USAGE_MEMORY_OK = (
    "已在記憶庫找到依據；個人化回答時標明來源（哪一筆記憶／哪個檔），"
    "不要改寫成記憶裡沒有的內容。"
)
_USAGE_MEMORY_NOT_FOUND = (
    "記憶庫中找不到此依據。可參考 candidates 的相近條目；確認無誤前不要"
    "宣稱『你記得 / 你曾說過』。若屬新事實，請走 propose_memory 提議後再引用。"
)
_USAGE_URL_EXTERNAL = (
    "URL 屬外部來源，本工具不做線上抓取。只引用你本回合實際以 web_extract / "
    "browser 抓取過的連結；勿憑印象杜撰網址。未抓取就先抓取再引用。"
)
_USAGE_EMPTY = "ref 為空，無可驗證的來源。"


# ---------------------------------------------------------------------------
# 主 handler
# ---------------------------------------------------------------------------


def verify_source(
    ref: str,
    source_kind: str | None = None,
    quoted_text: str | None = None,
    hermes_home: str | None = None,
) -> dict[str, Any]:
    """驗證來源是否可追溯（紅線#2）。回傳 dict，status 見下。

    status:
      * ``ok``        — memory：在記憶庫找到依據
      * ``not_found`` — memory：找不到（附 candidates 模糊候選）
      * ``external``  — url：外部來源，離線不可驗證（附引用紀律）
      * ``empty``     — ref 為空
    """
    ref = (ref or "").strip()
    kind = (source_kind or _detect_kind(ref)).lower()

    if not ref:
        return {
            "status": "empty",
            "source_kind": kind,
            "ref": "",
            "matched": False,
            "usage_instruction": _USAGE_EMPTY,
        }

    if kind == "url":
        return {
            "status": "external",
            "source_kind": "url",
            "ref": ref,
            "matched": False,
            "usage_instruction": _USAGE_URL_EXTERNAL,
        }

    # source_kind == "memory"
    home = _hermes_home(hermes_home)
    target = quoted_text if quoted_text else ref
    q_norm = _strip_for_compare(target)

    files = _memory_files(home)
    if q_norm:
        for f in files:
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                continue
            if q_norm in _strip_for_compare(content):
                return {
                    "status": "ok",
                    "source_kind": "memory",
                    "ref": ref,
                    "matched": True,
                    "matched_in": f.name,
                    "matched_excerpt": _matching_excerpt(content, q_norm)[:200],
                    "usage_instruction": _USAGE_MEMORY_OK,
                }

    # 找不到 → 蒐集模糊候選（跨所有記憶檔的行）
    candidates: list[str] = []
    lines: list[str] = []
    for f in files:
        try:
            lines.extend(
                ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()
            )
        except Exception:
            continue
    if lines:
        candidates = difflib.get_close_matches(target, lines, n=3, cutoff=0.4)

    return {
        "status": "not_found",
        "source_kind": "memory",
        "ref": ref,
        "matched": False,
        "candidates": candidates,
        "usage_instruction": _USAGE_MEMORY_NOT_FOUND,
    }


# ---------------------------------------------------------------------------
# Toolset registration（仿 verify_citation 的 register 形狀）
# ---------------------------------------------------------------------------


def _verify_source_handler(args: Any, **kwargs: Any) -> str:
    args = args if isinstance(args, dict) else {}
    try:
        result = verify_source(
            ref=args.get("ref", ""),
            source_kind=args.get("source_kind"),
            quoted_text=args.get("quoted_text"),
            hermes_home=args.get("hermes_home"),
        )
        return json.dumps({"success": True, **result}, ensure_ascii=False, indent=2)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2)


registry.register(
    name="VerifySource",
    toolset="source-guard",
    schema={
        "name": "VerifySource",
        "description": (
            "驗證回答依據是否可追溯（設計紅線#2 來源透明）。兩種 source_kind："
            "memory（個人化回答）— 對本地記憶庫做標準化內容比對，回 ok/not_found；"
            "url（研究型回答）— 外部連結離線不可驗證，回 external 並提醒只引用本回合"
            "實際抓取過的連結。未提供 source_kind 時依 ref 是否為 http(s) 自動判定。"
            "個人化回答引用記憶前、或附上外部連結前呼叫，避免杜撰來源。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "來源識別：記憶為關鍵字/該筆內容；外部為 URL。",
                },
                "source_kind": {
                    "type": "string",
                    "enum": ["memory", "url"],
                    "description": "來源種類；省略則依 ref 自動判定。",
                },
                "quoted_text": {
                    "type": "string",
                    "description": (
                        "（memory）你計畫據此宣稱的文字；提供它會以內容比對驗證，"
                        "比僅憑 ref 更嚴格。"
                    ),
                },
                "hermes_home": {"type": "string"},
            },
            "required": ["ref"],
        },
    },
    handler=_verify_source_handler,
    check_fn=lambda: True,
    description="來源可追溯性驗證（設計紅線#2）",
    emoji="🔎",
)
