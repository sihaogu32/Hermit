"""Consent Center plugin — backend API routes (Stage C/D).

Mounted at /api/plugins/consent-center/ by the dashboard plugin system.

模式：machine proposes / human confirms（移植自 legal-kb-admin）。

責任邊界（紅線#5）：
- 讀 HERMES_HOME/consent_proposals/*.json（connector 經 propose tool 寫入的待確認 staging）
- 讀 HERMES_HOME/consent_history/confirm_*.json（confirm 後的 audit 紀錄）
- POST confirm 先確認 staging 檔存在，再同步呼叫 tools.consent_memory.apply_proposal
  （寫入受管記憶的唯一入口；apply 永遠不是 agent tool）
- POST cancel 刪 staging 檔

不做：寫入函式本身（在 tools.consent_memory）、cron 排程、進度 polling。
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hermes_constants import get_hermes_home
from tools import consent_event, consent_memory

router = APIRouter()


def _proposals_dir() -> Path:
    return get_hermes_home().expanduser().resolve() / "consent_proposals"


def _history_dir() -> Path:
    return get_hermes_home().expanduser().resolve() / "consent_history"


def _safe_filename(name: str) -> str:
    """禁止跨目錄存取；只允許單一檔名。"""
    if not name or "/" in name or "\\" in name or ".." in name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail=f"invalid filename: {name!r}")
    return name


@router.get("/proposals")
async def list_proposals() -> dict[str, Any]:
    """列舉 consent_proposals/*.json，依 created_at 倒序，每筆回精簡欄位。"""
    try:
        proposals_dir = _proposals_dir()
        if not proposals_dir.exists():
            return {"proposals": []}
        out: list[dict[str, Any]] = []
        for p in proposals_dir.glob("*.json"):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({
                "proposal_id": payload.get("proposal_id") or p.stem,
                "created_at": payload.get("created_at", ""),
                "source": payload.get("source", ""),
                "status": payload.get("status", ""),
                "summary": payload.get("summary", {}),
            })
        out.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return {"proposals": out}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str) -> dict[str, Any]:
    """回完整 proposal payload（含 items 與 item.source_ref）。"""
    try:
        _safe_filename(proposal_id)
        path = _proposals_dir() / f"{proposal_id}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"proposal not found: {proposal_id}")
        return json.loads(path.read_text(encoding="utf-8"))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


class ConfirmBody(BaseModel):
    selected_item_ids: list[str] | None = None


@router.post("/proposals/{proposal_id}/confirm")
async def confirm_proposal(proposal_id: str, body: ConfirmBody | None = None) -> dict[str, Any]:
    """先檢查 staging 檔存在（不存在 404，且不呼叫任何 applier），
    存在則依 proposal 的 ``applier`` 欄位分派到對應 applier 寫入。

    分派（單一同意中心、單一確認 UI，但各 applier 落不同 store）：
    - applier == "calendar_event" → consent_event.apply_event（寫 calendar/events.json）
    - 其餘（含無 applier 欄位的舊 proposal） → consent_memory.apply_proposal（寫受管記憶）

    body 為空 → selected_item_ids=None → 全部套用。
    成功回 applier 結果 dict；apply 失敗回 500 + traceback。
    """
    try:
        _safe_filename(proposal_id)
        # 紅線守門：staging 不存在則 404，且絕不觸發任何寫入路徑。
        proposal_path = _proposals_dir() / f"{proposal_id}.json"
        if not proposal_path.exists():
            raise HTTPException(status_code=404, detail=f"proposal not found: {proposal_id}")

        b = body or ConfirmBody()
        applier = json.loads(proposal_path.read_text(encoding="utf-8")).get("applier")
        if applier == consent_event.APPLIER:
            result = consent_event.apply_event(
                proposal_id,
                selected_item_ids=b.selected_item_ids,
            )
        else:
            result = consent_memory.apply_proposal(
                proposal_id,
                selected_item_ids=b.selected_item_ids,
            )
        return result
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.post("/proposals/{proposal_id}/cancel")
async def cancel_proposal(proposal_id: str) -> dict[str, Any]:
    """直接刪 staging proposal 檔；404 if 不存在。"""
    try:
        _safe_filename(proposal_id)
        path = _proposals_dir() / f"{proposal_id}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"proposal not found: {proposal_id}")
        path.unlink()
        return {"proposal_id": proposal_id, "deleted": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.get("/history")
async def list_history(limit: int = 50) -> dict[str, Any]:
    """列 consent_history/confirm_*.json 最新 N 筆精簡欄位，倒序。"""
    try:
        log_dir = _history_dir()
        if not log_dir.exists():
            return {"history": []}
        files = sorted(log_dir.glob("confirm_*.json"), reverse=True)[: max(0, int(limit))]
        items: list[dict[str, Any]] = []
        for p in files:
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            items.append({
                "filename": p.name,
                "written_at": payload.get("written_at", ""),
                "counts": payload.get("counts", {}),
            })
        return {"history": items}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.get("/history/{filename}")
async def get_history(filename: str) -> dict[str, Any]:
    """回單筆 audit 完整 payload；filename 須過 _safe_filename 且
    startswith("confirm_") and endswith(".json")，否則 400；不存在 404。"""
    try:
        _safe_filename(filename)
        if not filename.startswith("confirm_") or not filename.endswith(".json"):
            raise HTTPException(status_code=400, detail=f"invalid audit filename: {filename}")
        path = _history_dir() / filename
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"audit not found: {filename}")
        return json.loads(path.read_text(encoding="utf-8"))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())
