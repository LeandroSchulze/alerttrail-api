# app/routers/billing_subscriptions.py
from __future__ import annotations

from datetime import datetime, timedelta
import os

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user_cookie
from app.security.billing_guard import normalize_user_plan

router = APIRouter(tags=["billing-trial"])


@router.post("/billing/trial/start", include_in_schema=False)
def start_trial(
    request: Request,
    db: Session = Depends(get_db),
    current=Depends(get_current_user_cookie),
):
    """
    Activa el periodo de prueba PRO para el usuario actual.

    Reglas:
      - Si tiene PRO pago activo (subscription), no se le activa trial.
      - Si ya tuvo trial y no está en uno activo, no se reactiva.
      - Si el trial sigue activo, devolvemos la info existente.
      - Por defecto son 30 días, configurable con TRIAL_DAYS.
    """
    user: User | None = db.query(User).filter(User.id == current["sub"]).first()
    if not user:
        return JSONResponse({"ok": False, "error": "user_not_found"}, status_code=404)

    user = normalize_user_plan(db, user)
    now = datetime.utcnow()

    pro_source = (getattr(user, "pro_source", None) or "").lower()
    pro_expires_at = getattr(user, "pro_expires_at", None)
    trial_expires_at = getattr(user, "trial_expires_at", None)
    had_trial = bool(getattr(user, "had_trial", False))

    has_paid_pro = pro_source == "subscription" and pro_expires_at and pro_expires_at > now
    if has_paid_pro:
        return JSONResponse(
            {
                "ok": False,
                "error": "already_pro",
                "message": "Ya tenés un plan PRO activo.",
            },
            status_code=400,
        )

    has_trial_pro = pro_source == "trial" and pro_expires_at and pro_expires_at > now
    if has_trial_pro:
        days = getattr(user, "trial_days", None) or 30
        return {
            "ok": True,
            "trial_activated": False,
            "trial_days": days,
            "expires_at": pro_expires_at.isoformat(),
        }

    if had_trial and not has_trial_pro:
        return JSONResponse(
            {
                "ok": False,
                "error": "trial_already_used",
                "message": "Ya usaste tu periodo de prueba.",
            },
            status_code=400,
        )

# Soporta tanto TRIAL_DAYS como TRIAL_PRO_DAYS (legacy)
days_env = os.getenv("TRIAL_DAYS") or os.getenv("TRIAL_PRO_DAYS")
try:
    days_env_val = int(days_env) if days_env is not None else None
except Exception:
    days_env_val = None

days = days_env_val or getattr(user, "trial_days", None) or 30


    trial_start = now
    trial_end = now + timedelta(days=days)

    user.trial_started_at = trial_start
    user.trial_expires_at = trial_end
    user.trial_days = days
    user.pro_source = "trial"
    user.pro_expires_at = trial_end
    user.had_trial = True

    plan_raw = (getattr(user, "plan", None) or "FREE").upper()
    if plan_raw in {"FREE", "BASIC", ""}:
        user.plan = "PRO"

    if hasattr(user, "is_pro"):
        user.is_pro = True

    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "ok": True,
        "trial_activated": True,
        "trial_days": days,
        "expires_at": trial_end.isoformat(),
    }
