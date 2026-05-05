# app/routers/push.py
from __future__ import annotations
import os
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PushSubscription
from app.security import get_current_user_cookie_optional

router = APIRouter(prefix="/push", tags=["push"])

def _extract_uid(user: Any) -> Optional[int]:
    if not user or not isinstance(user, dict): return None
    raw_id = user.get("id") or user.get("user_id") or user.get("sub")
    try: return int(raw_id)
    except: return None

@router.get("/vapid-public")
def vapid_public():
    # Coincide con el nombre en tu captura de pantalla 2026-05-05 043455.jpg
    return {"vapidPublicKey": os.getenv("VAPID_PUBLIC_KEY", "")}

@router.post("/subscribe")
async def push_subscribe(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie_optional(request)
    if not user:
        return JSONResponse({"ok": False, "msg": "No session"}, status_code=401)

    payload = await request.json()
    uid = _extract_uid(user)
    
    if not uid or "endpoint" not in payload:
        return JSONResponse({"ok": False}, status_code=400)

    # Evitamos duplicados: si el endpoint ya existe para este usuario, no lo duplicamos
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
