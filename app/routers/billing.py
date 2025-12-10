# app/routers/billing.py
from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user_cookie
from app.security.billing_guard import normalize_user_plan

router = APIRouter(prefix="/billing", tags=["billing"])


def _as_int(name: str, default: int) -> int:
    v = (os.getenv(name, "") or "").strip()
    try:
        return int(v.replace("_", "").replace(",", ""))
    except Exception:
        return int(default)


def _as_float(name: str, default: float) -> float:
    v = (os.getenv(name, "") or "").strip()
    try:
        return float(v.replace("_", "").replace(",", ""))
    except Exception:
        return float(default)


def _pricing_ctx() -> Dict[str, Any]:
    """Contexto de precios inyectado en billing.html."""
    price_month = _as_float("PRO_PRICE_USD", float(os.getenv("PLAN_PRICE", "10") or 10.0))
    price_year = _as_float("PRO_PRICE_YEAR_USD", 96.0)  # 20% OFF aprox.
    biz_included = _as_int("BIZ_INCLUDED_SEATS", 25)
    biz_extra = _as_float("BIZ_EXTRA_SEAT_USD", 5.0)
    trial_days = _as_int("TRIAL_DAYS", 30)

    return {
        "price_month": price_month,
        "price_year": price_year,
        "biz_included": biz_included,
        "biz_extra": biz_extra,
        "trial_days": trial_days,
    }


@router.get("/subscriptions", response_class=HTMLResponse)
def billing_subscriptions(
    request: Request,
    user=Depends(get_current_user_cookie),
):
    ctx: Dict[str, Any] = {"request": request, "user": user}
    ctx.update(_pricing_ctx())
    return request.app.state.templates.TemplateResponse("billing.html", ctx)


@router.get("/me")
def billing_me(
    db: Session = Depends(get_db),
    current=Depends(get_current_user_cookie),
):
    """Devuelve el estado de plan del usuario actual para la UI de facturación."""
    user: User | None = db.query(User).filter(User.id == current["sub"]).first()
    if not user:
        return JSONResponse({"ok": False, "error": "user_not_found"}, status_code=404)

    user = normalize_user_plan(db, user)

    now = datetime.utcnow()
    pro_expires_at: datetime | None = getattr(user, "pro_expires_at", None)
    trial_started_at: datetime | None = getattr(user, "trial_started_at", None)
    trial_expires_at: datetime | None = getattr(user, "trial_expires_at", None)

    is_pro = False
    remaining_days = None
    remaining_hours = None
    if pro_expires_at and pro_expires_at > now:
        is_pro = True
        delta = pro_expires_at - now
        total_seconds = max(0, int(delta.total_seconds()))
        remaining_days = total_seconds // 86400
        remaining_hours = (total_seconds % 86400) // 3600

    data = {
        "ok": True,
        "email": user.email,
        "plan": (user.plan or "FREE").upper(),
        "is_pro": is_pro,
        "pro_expires_at": pro_expires_at.isoformat() if pro_expires_at else None,
        "remaining_days": remaining_days,
        "remaining_hours": remaining_hours,
        "trial_started_at": trial_started_at.isoformat() if trial_started_at else None,
        "trial_expires_at": trial_expires_at.isoformat() if trial_expires_at else None,
        "had_trial": bool(getattr(user, "had_trial", False)),
        "pro_source": getattr(user, "pro_source", None),
        "trial_days": getattr(user, "trial_days", None),
    }
    return JSONResponse(data)


@router.get("/history")
def billing_history():
    """Stub simple para historial de pagos.

    Si tenés montado app.routers.payments_history con el mismo path,
    ese router puede sobrescribir este comportamiento. En ese caso,
    este endpoint queda como compatibilidad.
    """
    return JSONResponse({"ok": True, "items": []})
