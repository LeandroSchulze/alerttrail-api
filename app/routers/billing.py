# app/routers/billing.py
from __future__ import annotations

import os
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, HTMLResponse

from app.ui import templates
from app.security import get_current_user_cookie
from app.i18n import get_lang_from_request, jinja_t

router = APIRouter(prefix="/billing", tags=["billing"])


def _float_env(name: str, default: float) -> float:
    try:
        v = os.getenv(name)
        if v is None or v == "":
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _int_env(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        if v is None or v == "":
            return int(default)
        return int(float(v))
    except Exception:
        return int(default)


@router.get("/subscriptions", response_class=HTMLResponse)
def subscriptions(request: Request, user=Depends(get_current_user_cookie)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang_from_request(request)

    # Defaults (se pueden pisar por ENV)
    # PRO_PRICE_MONTH=10
    # PRO_PRICE_YEAR=96
    # PRO_YEAR_DISC_PCT=20
    price_month = _float_env("PRO_PRICE_MONTH", 10.0)

    # Si no viene price_year, lo calculamos con descuento default 20%
    disc_pct = _int_env("PRO_YEAR_DISC_PCT", 20)  # 0..90 recomendado
    disc_pct = max(0, min(disc_pct, 90))

    computed_year = round(price_month * 12 * (1 - disc_pct / 100.0), 2)
    price_year = _float_env("PRO_PRICE_YEAR", computed_year)

    currency = os.getenv("BILLING_CURRENCY", "USD")
    billing_period_label = os.getenv("BILLING_PERIOD_LABEL", "mes")

    plan = (user.get("plan") or "").upper() or ("PRO" if user.get("is_admin") else "FREE")
    is_pro = bool(user.get("is_pro") or plan == "PRO" or user.get("is_admin"))
    is_admin = bool(user.get("is_admin"))

    return templates.TemplateResponse(
        "billing_subscriptions.html",
        {
            "request": request,
            "lang": lang,
            "t": jinja_t,
            "current_user": user,

            # ✅ variables que el template usa
            "price_month": price_month,
            "price_year": price_year,
            "disc_pct": disc_pct,

            # extras (por si el template las referencia)
            "currency": currency,
            "billing_period_label": billing_period_label,
            "plan": plan,
            "is_pro": is_pro,
            "is_admin": is_admin,
        },
    )
