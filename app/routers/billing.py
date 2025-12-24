# app/routers/billing.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.security import get_current_user_cookie
from app.ui import templates
from app.i18n import get_lang, t

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/subscriptions", response_class=HTMLResponse, include_in_schema=False)
def subscriptions(request: Request, user=Depends(get_current_user_cookie)):
    lang = get_lang(request)

    current_plan = (getattr(user, "plan", None) or "FREE").upper()
    is_pro = bool(getattr(user, "is_pro", False)) or current_plan == "PRO"

    had_trial = bool(getattr(user, "had_trial", False))
    trial_available = (not is_pro) and (not had_trial)

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
            "had_trial": had_trial,
            "trial_available": trial_available,
        },
    )


# -------------------------------------------------------------------
# ✅ Checkout placeholder (pre Stripe/MercadoPago)
#    Fix directo al error de /billing/checkout?plan=...
# -------------------------------------------------------------------
@router.get("/checkout", response_class=HTMLResponse, include_in_schema=False)
def checkout(request: Request, plan: str = "PRO", user=Depends(get_current_user_cookie)):
    lang = get_lang(request)
    plan = (plan or "PRO").upper().strip()

    if plan not in ("PRO", "BIZ", "BUSINESS", "EMPRESA", "EMPRESAS"):
        plan = "PRO"

    plan_norm = "BIZ" if plan in ("BIZ", "BUSINESS", "EMPRESA", "EMPRESAS") else "PRO"

    return templates.TemplateResponse(
        "billing_checkout.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "user": user,
            "current_user": user,
            "plan": plan_norm,
        },
    )


@router.get("/payments", response_class=HTMLResponse, include_in_schema=False)
def payments(request: Request, user=Depends(get_current_user_cookie)):
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
