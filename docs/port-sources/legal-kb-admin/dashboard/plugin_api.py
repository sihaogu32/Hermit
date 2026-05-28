"""Legal KB Admin plugin — backend API routes (Stage C).

Mounted at /api/plugins/legal-kb-admin/ by the dashboard plugin system.

責任邊界：
- 讀 HERMES_HOME/legal_kb_scans/*.json（cron 觸發 agent 寫入的待確認 scan）
- 讀 wiki/legal/logs/change/extract_*.json（apply 後的歷史 changelog）
- POST confirm 同步呼叫 tools.legal_kb.run_apply_selected（Task 5 才接）
- POST cancel 刪 scan 檔（Task 5 才接）

不做：cron 排程 CRUD、立即觸發、進度 polling、SSE — 階段 C 範圍外。
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hermes_constants import get_hermes_home
from tools import legal_kb as _legal_kb
from tools.legal_kb import get_legal_kb_dir

router = APIRouter()


def _scans_dir() -> Path:
    return get_hermes_home().expanduser().resolve() / "legal_kb_scans"


def _history_dir() -> Path:
    """changelog dir 是 KB dir 的 sibling logs/change，與 _write_change_log 對齊。"""
    return get_legal_kb_dir().parent / "logs" / "change"


def _safe_filename(name: str) -> str:
    """禁止跨目錄存取；只允許單一檔名。"""
    if not name or "/" in name or "\\" in name or ".." in name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail=f"invalid filename: {name!r}")
    return name


@router.get("/scans")
async def list_scans() -> dict[str, Any]:
    """列舉 legal_kb_scans/*.json，依 created_at 倒序。"""
    try:
        scans_dir = _scans_dir()
        if not scans_dir.exists():
            return {"scans": []}
        out: list[dict[str, Any]] = []
        for p in scans_dir.glob("*.json"):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({
                "scan_id": payload.get("scan_id") or p.stem,
                "created_at": payload.get("created_at", ""),
                "source_used": payload.get("source_used", ""),
                "summary": payload.get("summary", {}),
            })
        out.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return {"scans": out}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.get("/scans/{scan_id}")
async def get_scan(scan_id: str) -> dict[str, Any]:
    """回完整 scan dump payload（含 scan.article_diffs / new / changed / obsolete）。"""
    try:
        _safe_filename(scan_id)
        path = _scans_dir() / f"{scan_id}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"scan not found: {scan_id}")
        return json.loads(path.read_text(encoding="utf-8"))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.get("/history")
async def list_history(limit: int = 50) -> dict[str, Any]:
    """列 wiki/legal/logs/change/extract_*.json 最新 N 筆精簡欄位。"""
    try:
        log_dir = _history_dir()
        if not log_dir.exists():
            return {"history": []}
        files = sorted(log_dir.glob("extract_*.json"), reverse=True)[: max(0, int(limit))]
        items: list[dict[str, Any]] = []
        for p in files:
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            items.append({
                "filename": p.name,
                "timestamp_utc": payload.get("timestamp_utc", ""),
                "counts": payload.get("counts", {}),
            })
        return {"history": items}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.get("/history/{filename}")
async def get_history(filename: str) -> dict[str, Any]:
    """回單筆 changelog 完整 payload（含 article_diffs）。"""
    try:
        _safe_filename(filename)
        if not filename.startswith("extract_") or not filename.endswith(".json"):
            raise HTTPException(status_code=400, detail=f"invalid changelog filename: {filename}")
        path = _history_dir() / filename
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"changelog not found: {filename}")
        return json.loads(path.read_text(encoding="utf-8"))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


class ConfirmBody(BaseModel):
    laws: list[str] | None = None
    delete_obsolete: bool = False


@router.post("/scans/{scan_id}/confirm")
async def confirm_scan(scan_id: str, body: ConfirmBody | None = None) -> dict[str, Any]:
    """同步呼叫 tools.legal_kb.run_apply_selected：套用整批或勾選法規。

    Body 為空 → 全部套用、不刪 obsolete。
    成功回 {applied, summaries, changelog_path}；失敗回 500 + traceback。
    """
    try:
        _safe_filename(scan_id)
        if not (_scans_dir() / f"{scan_id}.json").exists():
            raise HTTPException(status_code=404, detail=f"scan not found: {scan_id}")

        b = body or ConfirmBody()
        result = _legal_kb.run_apply_selected(
            scan_id,
            laws=b.laws,
            delete_obsolete=b.delete_obsolete,
        )
        return result
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.post("/scans/{scan_id}/cancel")
async def cancel_scan(scan_id: str) -> dict[str, Any]:
    """直接刪 scan dump 檔；404 if 不存在。"""
    try:
        _safe_filename(scan_id)
        path = _scans_dir() / f"{scan_id}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"scan not found: {scan_id}")
        path.unlink()
        return {"scan_id": scan_id, "deleted": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())
