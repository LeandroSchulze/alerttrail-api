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


@router.get("/subscriptions", response_class=HTMLResponse)
def subscriptions(request: Request, user=Depends(get_current_user_cookie)):
    # Si no está logueado, mandamos al login web
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang_from_request(request)

    # Defaults (podés sobreescribir con ENV en Render)
    # Ej: PRO_PRICE_MONTH=10
    price_month = _float_env("PRO_PRICE_MONTH", 10.0)

    # Si el template usa más variables, las dejamos listas:
    currency = os.getenv("BILLING_CURRENCY", "USD")
    billing_period_label = os.getenv("BILLING_PERIOD_LABEL", "mes")  # "mes" / "month"

    # Info útil para UI
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

            # ✅ FIX: variables que el template espera
            "price_month": price_month,

            # extras (por si el template las referencia ahora o después)
            "currency": currency,
            "billing_period_label": billing_period_label,
            "plan": plan,
            "is_pro": is_pro,
            "is_admin": is_admin,
        },
    )
