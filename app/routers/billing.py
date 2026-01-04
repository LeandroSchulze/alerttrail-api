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
        if v is None or str(v).strip() == "":
            return float(default)
        return float(str(v).strip())
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        if v is None or str(v).strip() == "":
            return int(default)
        return int(str(v).strip())
    except Exception:
        return int(default)


@router.get("/subscriptions", response_class=HTMLResponse, include_in_schema=False)
def subscriptions(request: Request, user=Depends(get_current_user_cookie_optional)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)

    current_plan = (user.get("plan") or "FREE").upper()
    role = (user.get("role") or "").lower()
    is_admin = role == "admin"
    is_pro = bool(user.get("is_pro", False)) or current_plan == "PRO" or is_admin

    had_trial = bool(user.get("had_trial", False))
    trial_available = (not is_pro) and (not had_trial)

    # ✅ Variables que el template billing_subscriptions.html espera
    plan = current_plan
    currency = os.getenv("BILLING_CURRENCY_SYMBOL", "$")

    # Precios (defaults seguros). Si querés, podés setearlos en Render como ENV.
    price_month = _env_float("PRICE_PRO_MONTH", 9.99)
    disc_pct = _env_int("BILLING_ANNUAL_DISCOUNT_PCT", 20)
    # Año con descuento (por ejemplo 20% OFF)
    price_year = _env_float("PRICE_PRO_YEAR", round(price_month * 12 * (1 - (disc_pct / 100.0)), 2))

    biz_included = _env_int("BIZ_INCLUDED", 10)
    biz_extra = _env_float("BIZ_EXTRA_PRICE", 2.00)

    return templates.TemplateResponse(
        "billing_subscriptions.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "current_user": user,
            "user": user,
            "current_plan": current_plan,
            "is_pro": is_pro,
            "is_admin": is_admin,
            "had_trial": had_trial,
            "trial_available": trial_available,
            # template vars:
            "plan": plan,
            "currency": currency,
            "price_month": price_month,
            "price_year": price_year,
            "disc_pct": disc_pct,
            "biz_included": biz_included,
            "biz_extra": biz_extra,
        },
    )


@router.get("/checkout", response_class=HTMLResponse, include_in_schema=False)
def checkout(request: Request, plan: str = "PRO", user=Depends(get_current_user_cookie_optional)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)
    plan = (plan or "PRO").upper().strip()

    if plan not in ("PRO", "BIZ", "BUSINESS", "EMPRESA", "EMPRESAS"):
        plan = "PRO"

    plan_norm = "BIZ" if plan in ("BIZ", "BUSINESS", "EMPRESA", "EMPRESAS") else "PRO"

    # ✅ Detalles del plan (desde ENV para que coincida con el backend)
    currency = (os.getenv("PLAN_CURRENCY") or "USD").upper()
    currency_symbol = "$" if currency == "USD" else currency

    # Defaults iguales a lo que configuraste
    pro_price = float(os.getenv("PRO_PRICE_USD") or 15.0)
    biz_price = float(os.getenv("BIZ_PRICE_USD") or 99.0)
    biz_included = int(os.getenv("BIZ_INCLUDED_SEATS") or 25)
    biz_extra = float(os.getenv("BIZ_EXTRA_SEAT_USD") or 3.0)

    if plan_norm == "BIZ":
        price_month = biz_price
        included_seats = biz_included
        extra_seat_price = biz_extra
        init_point = f"/payments/subscribe?plan=BIZ&seats={included_seats}"
    else:
        price_month = pro_price
        included_seats = 1
        extra_seat_price = 0
        init_point = "/payments/subscribe?plan=PRO&seats=1"


    mp_access_token = (os.getenv("MP_ACCESS_TOKEN") or "").strip()
    mp_enabled = bool(mp_access_token)

    return templates.TemplateResponse(
        "billing_checkout.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "user": user,
            "current_user": user,
            "plan": plan_norm,
            "mp_enabled": mp_enabled,
            "init_point": init_point if mp_enabled else None,
            "error": None,
            # ✅ variables para mostrar detalle en el checkout
            "currency": currency,
            "currency_symbol": currency_symbol,
            "price_month": price_month,
            "included_seats": included_seats,
            "extra_seat_price": extra_seat_price,
        },
    )


@router.get("/payments", response_class=HTMLResponse, include_in_schema=False)
def payments(request: Request, user=Depends(get_current_user_cookie_optional)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)
    return templates.TemplateResponse(
        "billing_payments.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "current_user": user,
            "user": user,
        },
    )
