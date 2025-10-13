from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.security import get_current_user_cookie
from app.models import User

router = APIRouter(prefix="/promo", tags=["promo"])

TRIAL_DAYS = 5

@router.post("/start")
def start_trial(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
):
    if not user:
        raise HTTPException(401, "No autenticado")

    # Excluir empresas: si tiene org_id => es cuenta de organización
    if getattr(user, "org_id", None):
        raise HTTPException(403, "La promo es solo para cuentas individuales")

    if user.had_trial:
        raise HTTPException(409, "Ya utilizaste un trial anteriormente")

    now = datetime.now(timezone.utc)
    user.trial_started_at = now
    user.trial_expires_at = now + timedelta(days=TRIAL_DAYS)
    user.had_trial = True
    user.pro_source = "trial"
    db.commit()

    return {
        "ok": True,
        "trial_expires_at": user.trial_expires_at.isoformat(),
        "days": TRIAL_DAYS
    }

@router.get("/status")
def trial_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
):
    if not user:
        raise HTTPException(401, "No autenticado")

    active = False
    remaining_seconds = 0
    if user.trial_expires_at:
        delta = user.trial_expires_at - datetime.now(timezone.utc)
        active = delta.total_seconds() > 0
        remaining_seconds = max(0, int(delta.total_seconds()))

    return {
        "active": active,
        "trial_started_at": user.trial_started_at.isoformat() if user.trial_started_at else None,
        "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
        "remaining_seconds": remaining_seconds
    }
