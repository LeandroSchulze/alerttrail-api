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


def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


@router.get("/subscriptions", response_class=HTMLResponse)
def subscriptions(request: Request, user=Depends(get_current_user_cookie)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang_from_request(request)

    # -----------------------------
    # PRO defaults (configurable por ENV)
    # -----------------------------
    currency = os.getenv("BILLING_CURRENCY", "USD")

    pro_price_month = _float_env("PRO_PRICE_MONTH", 10.0)
    pro_disc_pct = _clamp_int(_int_env("PRO_YEAR_DISC_PCT", 20), 0, 90)
    pro_year_computed = round(pro_price_month * 12 * (1 - pro_disc_pct / 100.0), 2)
    pro_price_year = _float_env("PRO_PRICE_YEAR", pro_year_computed)

    # Variables legacy que tu template ya usa (price_month/price_year/disc_pct)
    price_month = pro_price_month
    price_year = pro_price_year
    disc_pct = pro_disc_pct

    # -----------------------------
    # BIZ defaults (para no romper template)
    # -----------------------------
    # Ejemplo: BIZ incluye N cuentas y cobra extra por asiento adicional
    biz_included = _int_env("BIZ_INCLUDED", 5)
    biz_extra = _float_env("BIZ_EXTRA_SEAT", 2.0)  # USD por mes por usuario extra

    biz_price_month = _float_env("BIZ_PRICE_MONTH", 25.0)
    biz_disc_pct = _clamp_int(_int_env("BIZ_YEAR_DISC_PCT", 20), 0, 90)
    biz_year_computed = round(biz_price_month * 12 * (1 - biz_disc_pct / 100.0), 2)
    biz_price_year = _float_env("BIZ_PRICE_YEAR", biz_year_computed)

    # -----------------------------
    # Estado del usuario (para mostrar plan actual)
    # -----------------------------
    plan = (user.get("plan") or "").upper()
    if not plan:
        plan = "PRO" if user.get("is_admin") else "FREE"

    is_admin = bool(user.get("is_admin"))
    is_pro = bool(user.get("is_pro") or plan in ("PRO", "BIZ") or is_admin)

    # trial (si el template lo referencia)
    trial_active = bool(user.get("trial_active", False))
    trial_ended = bool(user.get("trial_ended", False))
    trial_available = bool(user.get("trial_available", False))

    return templates.TemplateResponse(
        "billing_subscriptions.html",
        {
            "request": request,
            "lang": lang,
            "t": jinja_t,
            "current_user": user,

            # ---- PRO (legacy + explícito) ----
            "currency": currency,
            "price_month": price_month,
            "price_year": price_year,
            "disc_pct": disc_pct,
            "pro_price_month": pro_price_month,
            "pro_price_year": pro_price_year,
            "pro_disc_pct": pro_disc_pct,

            # ---- BIZ ----
            "biz_included": biz_included,
            "biz_extra": biz_extra,
            "biz_price_month": biz_price_month,
            "biz_price_year": biz_price_year,
            "biz_disc_pct": biz_disc_pct,

            # ---- Estado ----
            "plan": plan,
            "is_pro": is_pro,
            "is_admin": is_admin,

            # ---- Trial (por si aparece en template) ----
            "trial_active": trial_active,
            "trial_ended": trial_ended,
            "trial_available": trial_available,
        },
    )
