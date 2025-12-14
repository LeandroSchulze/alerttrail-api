# app/routers/billing_subscriptions.py
from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user_cookie, normalize_user_plan

router = APIRouter(tags=["billing-trial"])

@router.post("/billing/trial/start", include_in_schema=False)
def start_trial(
    request: Request,
    db: Session = Depends(get_db),
    current=Depends(get_current_user_cookie),
):
    """Activa el periodo de prueba PRO para el usuario actual.

    Reglas:
      - Si tiene PRO pago activo (pro_source='subscription' no vencido), no se activa trial.
      - Si ya tuvo trial y no está en uno activo, no se reactiva.
      - Si el trial sigue activo, devolvemos info existente.
      - Por defecto son 30 días, configurable con TRIAL_DAYS (o TRIAL_PRO_DAYS legacy).
    """
    user: User | None = db.query(User).filter(User.id == current["sub"]).first()
    if not user:
        return JSONResponse({"ok": False, "error": "user_not_found"}, status_code=404)

    user = normalize_user_plan(db, user)
    now = datetime.utcnow()

    pro_source = (getattr(user, "pro_source", None) or "").lower()
    pro_expires_at = getattr(user, "pro_expires_at", None)
    had_trial = bool(getattr(user, "had_trial", False))

    # 1) Si tiene PRO pago activo, no activar trial
    has_paid_pro = pro_source == "subscription" and pro_expires_at and pro_expires_at > now
    if has_paid_pro:
        return JSONResponse(
            {"ok": False, "error": "already_pro", "message": "Ya tenés un plan PRO activo."},
            status_code=400,
        )

    # 2) Si ya tiene trial activo, devolver estado
    has_trial_pro = pro_source == "trial" and pro_expires_at and pro_expires_at > now
    if has_trial_pro:
        days = getattr(user, "trial_days", None) or 30
        return {
            "ok": True,
            "trial_activated": False,
            "trial_days": days,
            "expires_at": pro_expires_at.isoformat(),
        }

    # 3) Si ya tuvo trial y no está activo, no reactivar
    if had_trial and not has_trial_pro:
        return JSONResponse(
            {"ok": False, "error": "trial_already_used", "message": "Ya usaste tu periodo de prueba."},
            status_code=400,
        )

    # 4) Determinar días de trial
    days_env = os.getenv("TRIAL_DAYS") or os.getenv("TRIAL_PRO_DAYS")
    try:
        days_env_val = int(days_env) if days_env is not None else None
    except Exception:
        days_env_val = None
    days = days_env_val or getattr(user, "trial_days", None) or 30

    # 5) Activar
    trial_start = now
    trial_end = now + timedelta(days=days)

    # Campos opcionales (según migraciones)
    if hasattr(user, "trial_started_at"):
        user.trial_started_at = trial_start
    if hasattr(user, "trial_expires_at"):
        user.trial_expires_at = trial_end
    if hasattr(user, "trial_days"):
        user.trial_days = days

    if hasattr(user, "pro_source"):
        user.pro_source = "trial"
    if hasattr(user, "pro_expires_at"):
        user.pro_expires_at = trial_end
    if hasattr(user, "had_trial"):
        user.had_trial = True

    plan_raw = (getattr(user, "plan", None) or "FREE").upper()
    if plan_raw in {"FREE", "BASIC", ""} and hasattr(user, "plan"):
        user.plan = "PRO"
    if hasattr(user, "is_pro"):
        user.is_pro = True

    db.add(user)
    db.commit()
    try:
        db.refresh(user)
    except Exception:
        pass

    return {"ok": True, "trial_activated": True, "trial_days": days, "expires_at": trial_end.isoformat()}
