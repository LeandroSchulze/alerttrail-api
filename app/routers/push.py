# app/routers/push.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.security import get_current_user_cookie_optional

router = APIRouter(prefix="/push", tags=["push"])

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

SUBS_FILE = MAIL_DATA_DIR / "push_subscriptions.json"


def _load() -> Dict[str, List[Dict[str, Any]]]:
    try:
        if not SUBS_FILE.exists():
            return {}
        data = json.loads(SUBS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: Dict[str, List[Dict[str, Any]]]) -> None:
    SUBS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _user_id(user: Dict[str, Any]) -> str:
    return str(user.get("id") or user.get("email") or "unknown")


@router.get("/config")
def push_config():
    return {"public_key": os.getenv("VAPID_PUBLIC_KEY", "")}


@router.get("/vapid-public")
def vapid_public():
    return {"vapidPublicKey": os.getenv("VAPID_PUBLIC_KEY", "")}


@router.post("/subscribe")
async def push_subscribe(request: Request):
    user = get_current_user_cookie_optional(request)
    if not user:
        return JSONResponse({"ok": False}, status_code=401)

    payload = await request.json()
    if not payload or "endpoint" not in payload:
        return JSONResponse({"ok": False}, status_code=400)

    data = _load()
    uid = _user_id(user)

    data.setdefault(uid, [])
    data[uid] = [p for p in data[uid] if p.get("endpoint") != payload.get("endpoint")]
    data[uid].append(payload)

    _save(data)
    return {"ok": True}
