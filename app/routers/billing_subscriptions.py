# app/routers/billing_subscriptions.py
from datetime import datetime, timedelta
from decimal import Decimal
import os

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User
from app.security import get_current_user_cookie

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helpers de precios desde ENV (con fallback seguros)
def _as_int(v, d):
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return d

def _as_money(v, d):
    try:
        return float(Decimal(str(v).replace(",", ".")))
    except Exception:
        return float(d)

def _pricing_ctx_from_env():
    # PRO
    if os.getenv("PLAN_PRICE_CENTS"):
        try:
            cents = int(os.getenv("PLAN_PRICE_CENTS", "1000"))
        except Exception:
            cents = 1000
        price_month = round(cents / 100.0, 2)
    else:
        price_month = round(_as_money(os.getenv("PLAN_PRICE", "10"), 10.0), 2)

    disc_pct = _as_int(os.getenv("PLAN_ANNUAL_DISCOUNT_PCT", "20"), 20)
    price_year = round(price_month * 12 * (1 - disc_pct / 100.0), 2)
    currency = (os.getenv("PLAN_CURRENCY", "USD") or "USD").upper()

    # BIZ
    biz_price = round(_as_money(os.getenv("BIZ_PRICE_MONTH_USD", "99"), 99.0), 2)
    biz_included = _as_int(os.getenv("BIZ_INCLUDED_SEATS", "25"), 25)
    biz_extra = round(_as_money(os.getenv("BIZ_EXTRA_SEAT_USD", "3"), 3.0), 2)

    return dict(
        price_month=price_month,
        price_year=price_year,
        disc_pct=disc_pct,
        currency=currency,
        biz_price=biz_price,
        biz_included=biz_included,
        biz_extra=biz_extra,
    )

@router.get("/billing/subscriptions", response_class=HTMLResponse)
def billing_subscriptions(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    # Buscar usuario actual
    u = db.query(User).filter(User.id == user["sub"]).first()

    # Normalizar plan (por si está vencido o trial)
    try:
        from app.security.billing_guard import normalize_user_plan
        if u:
            normalize_user_plan(db, u)
            db.refresh(u)
    except Exception:
        pass

    # Determinar plan efectivo
    raw_plan = ((u.plan if u else None) or "FREE").upper()
    is_admin = bool(getattr(u, "is_admin", False) or getattr(u, "is_superuser", False))
    is_pro   = bool(getattr(u, "is_pro", False))
    effective_plan = "PRO" if (is_admin or is_pro) else raw_plan

    ctx = {
        "request": request,
        "user": u,
        "is_admin": is_admin,
        "is_pro": is_pro,
        "plan": effective_plan,
        "raw_plan": raw_plan,
    }
    ctx.update(_pricing_ctx_from_env())

    return request.app.state.templates.TemplateResponse("billing_subscriptions.html", ctx)

# =========================
# Trial de 5 días (o el valor de TRIAL_DAYS)
# =========================
@router.post("/billing/trial/start", include_in_schema=False)
def start_trial(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    u: User = db.query(User).filter(User.id == user["sub"]).first()
    if not u:
        return JSONResponse({"ok": False, "error": "user not found"}, status_code=404)

    # Ya tuvo trial?
    if u.trial_started_at:
        return JSONResponse({"ok": False, "error": "trial_already_used"}, status_code=400)

    # Días de trial: ENV > user.trial_days > 5
    days_env = os.getenv("TRIAL_DAYS")
    try:
        days_env = int(days_env) if days_env is not None else None
    except Exception:
        days_env = None
    days = days_env or (u.trial_days or 5)

    now = datetime.utcnow()
    u.trial_started_at = now
    u.trial_days = days
    # Tratamos como PRO mientras dure el trial
    u.plan = "PRO"
    u.is_pro = True
    u.plan_expires = now + timedelta(days=days)
    db.add(u); db.commit()

    return {"ok": True, "trial_days": days, "expires_at": u.plan_expires.isoformat()}
