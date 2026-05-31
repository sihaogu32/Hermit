"""Calendar plugin — backend API routes.

Mounted at /api/plugins/calendar/ by the dashboard plugin system.

責任邊界（紅線#5）：
- 讀「合併視圖」（native + ICS 快取 + 選配 google）走 tools.calendar_read.merged_events。
- 原生事件的增刪改走 tools.calendar_store（events.json 的唯一 writer）；
  使用者在 dashboard 的手動操作＝本人即時的人工確認，故可直接寫原生 store。
- 外部來源（google / ICS）為唯讀鏡像：合併視圖會帶它們，但增刪改僅作用於原生事件
  （calendar_store 只認 events.json；對 google:/ics: 的 id 編輯會 KeyError → 404）。
- ICS 訂閱清單（subscriptions.json）只存 URL + 標籤；實際抓取/解析在下一段（需 icalendar），
  refresh 端點目前回 deferred stub。

不做：把事件寫回 Google（建/刪 Google 端事件）等對外回寫——首版不接（紅線#5）。
"""

from __future__ import annotations

import json
import os
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hermes_constants import get_hermes_home
from tools import calendar_read, calendar_store

router = APIRouter()

SUB_SCHEMA_VERSION = 1


def _calendar_dir() -> Path:
    return get_hermes_home().expanduser().resolve() / "calendar"


def _subscriptions_path() -> Path:
    return _calendar_dir() / "subscriptions.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    """禁止跨目錄/注入；事件與訂閱 id 只允許安全字元。"""
    if not value or "/" in value or "\\" in value or ".." in value:
        raise HTTPException(status_code=400, detail=f"invalid id: {value!r}")
    return value


# ─────────────────────────── events (合併視圖 + 原生 CRUD) ───────────────────────────


class EventBody(BaseModel):
    title: str
    start: str
    end: str | None = None
    all_day: bool = False
    location: str | None = None
    description: str | None = None


class EventPatch(BaseModel):
    title: str | None = None
    start: str | None = None
    end: str | None = None
    all_day: bool | None = None
    location: str | None = None
    description: str | None = None
    status: str | None = None


@router.get("/events")
async def list_events(
    start: str | None = None,
    end: str | None = None,
    days_ahead: int = 30,
    calendar_id: str = "primary",
) -> dict[str, Any]:
    """合併視圖（native + ICS + 選配 google），依 start 排序。

    傳 start/end（ISO-8601）給定任意視窗（月/週檢視）；省略時用 now .. now+days_ahead。
    """
    try:
        if start and end:
            return calendar_read.merged_events(start, end, calendar_id=calendar_id)
        return calendar_read.read_calendar_events(
            days_ahead=days_ahead, calendar_id=calendar_id
        )
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.post("/events")
async def create_event(body: EventBody) -> dict[str, Any]:
    """新增一筆原生事件（使用者手動操作＝人工確認）。"""
    try:
        return calendar_store.add_event(body.model_dump())
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.patch("/events/{event_id}")
async def update_event(event_id: str, body: EventPatch) -> dict[str, Any]:
    """修改原生事件；非原生（google:/ics:）或不存在 → 404。"""
    try:
        _safe_id(event_id)
        patch = {k: v for k, v in body.model_dump().items() if v is not None}
        return calendar_store.update_event(event_id, patch)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"event not found: {event_id}")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.delete("/events/{event_id}")
async def delete_event(event_id: str) -> dict[str, Any]:
    """刪除原生事件；非原生或不存在 → 404。"""
    try:
        _safe_id(event_id)
        if not calendar_store.delete_event(event_id):
            raise HTTPException(status_code=404, detail=f"event not found: {event_id}")
        return {"event_id": event_id, "deleted": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


# ─────────────────────────── ICS 訂閱（subscriptions.json） ───────────────────────────


class SubscriptionBody(BaseModel):
    url: str
    label: str | None = None


def _read_subscriptions() -> list[dict]:
    path = _subscriptions_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    subs = payload.get("subscriptions") if isinstance(payload, dict) else payload
    return list(subs) if isinstance(subs, list) else []


def _write_subscriptions(subs: list[dict]) -> None:
    path = _subscriptions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SUB_SCHEMA_VERSION, "subscriptions": subs}
    tmp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


@router.get("/subscriptions")
async def list_subscriptions() -> dict[str, Any]:
    try:
        return {"subscriptions": _read_subscriptions()}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.post("/subscriptions")
async def add_subscription(body: SubscriptionBody) -> dict[str, Any]:
    """新增一條 ICS 訂閱（只存 URL + 標籤；抓取/解析在下一段）。"""
    try:
        url = (body.url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="url is required")
        sub = {
            "id": uuid.uuid4().hex,
            "url": url,
            "label": (body.label or "").strip() or url,
            "created_at": _now_iso(),
        }
        subs = _read_subscriptions()
        subs.append(sub)
        _write_subscriptions(subs)
        return sub
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.delete("/subscriptions/{sub_id}")
async def delete_subscription(sub_id: str) -> dict[str, Any]:
    try:
        _safe_id(sub_id)
        subs = _read_subscriptions()
        remaining = [s for s in subs if s.get("id") != sub_id]
        if len(remaining) == len(subs):
            raise HTTPException(status_code=404, detail=f"subscription not found: {sub_id}")
        _write_subscriptions(remaining)
        return {"id": sub_id, "deleted": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.post("/subscriptions/{sub_id}/refresh")
async def refresh_subscription(sub_id: str) -> dict[str, Any]:
    """手動觸發 ICS 抓取——目前為 deferred stub（ICS 解析需 icalendar，下一段接上）。"""
    try:
        _safe_id(sub_id)
        if not any(s.get("id") == sub_id for s in _read_subscriptions()):
            raise HTTPException(status_code=404, detail=f"subscription not found: {sub_id}")
        return {
            "id": sub_id,
            "status": "deferred",
            "message": "ICS 解析在下一段（需 icalendar）；目前僅保存訂閱 URL。",
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())
