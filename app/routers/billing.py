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
from app.security import normalize_user_plan

router = APIRouter(prefix="/billing", tags=["billing"])

def _pricing_ctx() -> Dict[str, Any]:
    try:
        price_month = float(os.getenv("PLAN_PRICE", "10"))
    except Exception:
        price_month = 10.0
    try:
        disc_pct = int(os.getenv("PLAN_ANNUAL_DISCOUNT_PCT", "20"))
    except Exception:
        disc_pct = 20
    price_year = round(price_month * 12 * (1 - disc_pct / 100.0), 2)
    currency = (os.getenv("PLAN_CURRENCY", "USD") or "USD").upper()
    return dict(price_month=price_month, price_year=price_year, disc_pct=disc_pct, currency=currency)

@router.get("", response_class=HTMLResponse, include_in_schema=False)
def billing_page(request: Request, db: Session = Depends(get_db), current=Depends(get_current_user_cookie)):
    user: User | None = db.query(User).filter(User.id == current["sub"]).first()
    if user:
        user = normalize_user_plan(db, user)

    ctx = {"request": request, "user": current, "current_user": user, "page_title": "Facturación | AlertTrail"}
    ctx.update(_pricing_ctx())

    # Si existe Jinja templates en app.state.templates, la usa el main.py.
    templates = getattr(request.app.state, "templates", None)
    if templates is None:
        return HTMLResponse("<h1>Billing</h1><p>Templates no disponibles.</p>")

    try:
        return templates.TemplateResponse("billing.html", ctx)
    except Exception:
        # fallback mínimo
        return HTMLResponse("<h1>Billing</h1><p>No encontré billing.html</p>")

@router.get("/me")
def billing_me(request: Request, db: Session = Depends(get_db), current=Depends(get_current_user_cookie)):
    user: User | None = db.query(User).filter(User.id == current["sub"]).first()
    if not user:
        return JSONResponse({"ok": False, "error": "user_not_found"}, status_code=404)

    user = normalize_user_plan(db, user)

    data = {
        "ok": True,
        "user_id": getattr(user, "id", None),
        "email": getattr(user, "email", None),
        "plan": (getattr(user, "plan", None) or "FREE").upper(),
        "is_pro": bool(getattr(user, "is_pro", False)),
        "plan_expires": getattr(user, "plan_expires", None) or getattr(user, "pro_expires_at", None),
        "pro_expires_at": getattr(user, "pro_expires_at", None),
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
