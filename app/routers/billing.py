# app/routers/billing.py
from __future__ import annotations
import os
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.security import get_current_user_cookie_optional
from app.ui import templates
from app.i18n import get_lang, t

router = APIRouter(prefix="/billing", tags=["billing"])

def _env_float(name: str, default: float) -> float:
    try:
        v = os.getenv(name)
        if not v or "${{" in str(v): return float(default)
        return float(str(v).strip())
    except: return float(default)

def _env_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        if not v or "${{" in str(v): return int(default)
        return int(str(v).strip())
    except: return int(default)

@router.get("/subscriptions", response_class=HTMLResponse, include_in_schema=False)
def subscriptions(request: Request, user=Depends(get_current_user_cookie_optional)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)
    
    # FIX: Manejo seguro si user es dict o objeto SQLAlchemy
    def gv(obj, key, default=None):
        if isinstance(obj, dict): return obj.get(key, default)
        return getattr(obj, key, default)

    current_plan = (gv(user, "plan") or "FREE").upper()
    is_admin = gv(user, "role") == "admin" or gv(user, "is_admin", False)
    is_pro = gv(user, "is_pro", False) or current_plan in ("PRO", "BIZ") or is_admin
    had_trial = bool(gv(user, "trial_used", False))

    # Configuración de precios y asientos (Sincronizado con tus variables)
    currency = os.getenv("BILLING_CURRENCY_SYMBOL", "$")
    price_month = _env_float("PLAN_PRICE", 9.99)
    disc_pct = _env_int("PRO_ANNUAL_DISTCOUNT_PCT", 20)
    price_year = round(price_month * 12 * (1 - (disc_pct / 100.0)), 2)

    # Configuración Empresa (Los 25 asientos que pediste)
    biz_included = _env_int("BIZ_INCLUDED_SEATS", 25) 
    biz_extra = _env_float("BIZ_EXTRA_SET_USD", 3.00)
    biz_price = _env_float("BIZ_PRICE_MONTH_USD", 99.00)

    return templates.TemplateResponse("billing_subscriptions.html", {
        "request": request, "lang": lang, "t": t, "user": user,
        "current_plan": current_plan, "is_pro": is_pro, "is_admin": is_admin,
        "had_trial": had_trial, "trial_available": (not is_pro and not had_trial),
        "plan": current_plan, "currency": currency,
        "price_month": price_month, "price_year": price_year, "disc_pct": disc_pct,
        "biz_included": biz_included, "biz_extra": biz_extra, "biz_price": biz_price
    })

@router.get("/checkout", response_class=HTMLResponse, include_in_schema=False)
def checkout(request: Request, plan: str = "PRO", user=Depends(get_current_user_cookie_optional)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)
    plan = (plan or "PRO").upper().strip()
    plan_norm = "BIZ" if plan in ("BIZ", "BUSINESS", "EMPRESA", "EMPRESAS") else "PRO"

    if plan_norm == "BIZ":
        price = _env_float("BIZ_PRICE_MONTH_USD", 99.00)
        seats = _env_int("BIZ_INCLUDED_SEATS", 25)
        extra = _env_float("BIZ_EXTRA_SET_USD", 3.00)
        init_point = f"/payments/pay?plan=BIZ&seats={seats}"
    else:
        price = _env_float("PLAN_PRICE", 9.99)
        seats = 1
        extra = 0
        init_point = "/payments/pay?plan=PRO&seats=1"

    mp_enabled = bool(os.getenv("MP_ACCESS_TOKEN"))

    return templates.TemplateResponse("billing_checkout.html", {
        "request": request, "lang": lang, "t": t, "user": user,
        "plan": plan_norm, "mp_enabled": mp_enabled,
        "init_point": init_point if mp_enabled else None,
        "currency_symbol": os.getenv("BILLING_CURRENCY_SYMBOL", "$"),
        "price_month": price, "included_seats": seats, "extra_seat_price": extra,
    })
