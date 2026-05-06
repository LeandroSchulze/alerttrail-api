# app/routers/push.py
from __future__ import annotations
import os
import logging
from typing import Any, Dict, List, Optional # <--- IMPORTANTE: Asegurar Any y Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PushSubscription
from app.security import get_current_user_cookie_optional
from app.services.webpush import send_push

router = APIRouter(prefix="/push", tags=["push"])
log = logging.getLogger(__name__)

# --- HELPERS PARA COMPATIBILIDAD ---

def _load():
    return {}

def _extract_uid(user: Any) -> Optional[int]:
    if not user or not isinstance(user, dict): return None
    raw_id = user.get("id") or user.get("user_id") or user.get("sub")
    try: return int(raw_id)
    except: return None

def trigger_push_notification(user_id: str | int, title: str, body: str):
    return send_push(user_id=user_id, title=title, body=body)

# --- RUTAS ---

@router.get("/vapid-public")
def vapid_public():
    return {"vapidPublicKey": os.getenv("VAPID_PUBLIC_KEY", "")}

@router.post("/subscribe")
async def push_subscribe(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie_optional(request)
    if not user:
        return JSONResponse({"ok": False}, status_code=401)

    payload = await request.json()
    uid = _extract_uid(user)
    
    if not uid or "endpoint" not in payload:
        return JSONResponse({"ok": False}, status_code=400)

    existing = db.query(PushSubscription).filter(
        PushSubscription.user_id == uid,
        PushSubscription.endpoint == payload["endpoint"]
    ).first()

    if not existing:
        new_sub = PushSubscription(
            user_id=uid,
            endpoint=payload["endpoint"],
            p256dh=payload["keys"]["p256dh"],
            auth=payload["keys"]["auth"]
        )
        db.add(new_sub)
        db.commit()
    
    return {"ok": True}
