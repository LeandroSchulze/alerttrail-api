# app/routers/alerts_pro.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..security import get_current_user_cookie
from ..models_pro_alerts import ProAlertPref
from ..services.pro_alerts import ensure_pref, flush_if_needed, queue_or_push

router = APIRouter(prefix="/alerts-pro", tags=["alerts-pro"])

def _ensure_pro(user: User):
    if getattr(user, "plan", "").upper() != "PRO":
        raise HTTPException(status_code=403, detail="Solo para usuarios PRO")

@router.get("/prefs")
def get_prefs(db: Session = Depends(get_db), user: User = Depends(get_current_user_cookie)):
    _ensure_pro(user)
    pref = ensure_pref(db, user.id)
    return {
        "cooldown_min": pref.cooldown_min,
        "quiet_hours": pref.quiet_hours,
        "push_enabled": pref.push_enabled
    }

@router.post("/prefs")
def set_prefs(cooldown_min: int = 10, quiet_hours: str = "", push_enabled: bool = True,
              db: Session = Depends(get_db), user: User = Depends(get_current_user_cookie)):
    _ensure_pro(user)
    pref = ensure_pref(db, user.id)
    pref.cooldown_min = max(0, cooldown_min)
    pref.quiet_hours = (quiet_hours or "").strip()
    pref.push_enabled = bool(push_enabled)
    db.commit()
    return {"ok": True}

@router.post("/test")
def send_test(db: Session = Depends(get_db), user: User = Depends(get_current_user_cookie)):
    _ensure_pro(user)
    queue_or_push(db, user, title="AlertTrail PRO", body="Prueba de notificación PRO", url="/dashboard")
    return {"queued": True}

@router.post("/flush")
def flush_queue(db: Session = Depends(get_db), user: User = Depends(get_current_user_cookie)):
    _ensure_pro(user)
    flush_if_needed(db, user.id)
    return {"flushed": True}
