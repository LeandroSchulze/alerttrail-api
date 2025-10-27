# app/routers/billing_ui.py
from __future__ import annotations
import os
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.database import get_db
from app.security import get_current_user_cookie

router = APIRouter(tags=["billing-ui"])

def _as_int(env_name: str, default: int) -> int:
    v = (os.getenv(env_name, "") or "").strip()
    try:
        # admite "1000", "1_000", " 1000 "
        v = v.replace("_", "")
        return int(v)
    except Exception:
        return int(default)

def _as_str(env_name: str, default: str) -> str:
    v = (os.getenv(env_name) or default)
    return (v or default).strip()

def _pricing_ctx():
    cents = _as_int("PLAN_PRICE_CENTS", 1000)   # 1000 = USD 10
    price_month = round(cents / 100.0, 2)
    disc_pct = _as_int("PLAN_ANNUAL_DISCOUNT_PCT", 20)
    # clamp 0..95
    disc_pct = max(0, min(95, disc_pct))
    price_year = round(price_month * 12 * (1 - disc_pct / 100.0), 2)
    currency = (_as_str("PLAN_CURRENCY", "USD") or "USD").upper()
    return dict(price_month=price_month, price_year=price_year,
                disc_pct=disc_pct, currency=currency)

def _ctx(request: Request, user):
    ctx = {"request": request, "user": user, "page_title": "Mi Suscripción | AlertTrail"}
    ctx.update(_pricing_ctx())
    # algunos templates esperan estas claves; definilas para evitar UndefinedError
    ctx["biz_extra"] = ctx.get("biz_extra", "")
    return ctx

@router.get("/billing", response_class=HTMLResponse, include_in_schema=False)
def billing_page(request: Request, db=Depends(get_db), user=Depends(get_current_user_cookie)):
    return request.app.state.templates.TemplateResponse("billing.html", _ctx(request, user))

@router.get("/account/billing", response_class=HTMLResponse, include_in_schema=False)
def billing_page_legacy(request: Request, db=Depends(get_db), user=Depends(get_current_user_cookie)):
    return request.app.state.templates.TemplateResponse("billing.html", _ctx(request, user))

# ⚠️ Evita redirección y sirve directamente el mismo template
@router.get("/billing/subscriptions", response_class=HTMLResponse, include_in_schema=False)
def billing_subscriptions_alias(request: Request, db=Depends(get_db), user=Depends(get_current_user_cookie)):
    return request.app.state.templates.TemplateResponse("billing.html", _ctx(request, user))
