# app/routers/billing_ui.py
from __future__ import annotations
import os
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.database import get_db
from app.security import get_current_user_cookie

router = APIRouter(tags=["billing-ui"])

def _as_int(env_name: str, default: int) -> int:
    v = os.getenv(env_name, "")
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return int(default)

def _as_money(env_name: str, default: float) -> float:
    """
    Convierte env a número (float) de forma segura.
    Acepta "10", "10.0", "10,0" y también centavos si viene PLAN_PRICE_CENTS.
    """
    v = os.getenv(env_name, "")
    if not v:
        return float(default)
    try:
        v = v.replace(",", ".")
        return float(Decimal(v))
    except Exception:
        return float(default)

def _pricing_ctx():
    """
    Devuelve TODO lo que el template billing.html necesita, con tipos correctos.
    - price_month / price_year / disc_pct / currency
    - biz_price / biz_included / biz_extra
    """
    # Precio PRO mensual
    if os.getenv("PLAN_PRICE_CENTS"):
        try:
            cents = int(os.getenv("PLAN_PRICE_CENTS", "1000"))
        except Exception:
            cents = 1000
        price_month = round(cents / 100.0, 2)
    else:
        price_month = round(_as_money("PLAN_PRICE", 10.0), 2)

    # Descuento anual
    disc_pct = _as_int("PLAN_ANNUAL_DISCOUNT_PCT", 20)
    price_year = round(price_month * 12 * (1 - disc_pct / 100.0), 2)

    currency = (os.getenv("PLAN_CURRENCY", "USD") or "USD").upper()

    # Business
    biz_price = round(_as_money("BIZ_PRICE_MONTH_USD", 99.0), 2)
    biz_included = _as_int("BIZ_INCLUDED_SEATS", 25)
    biz_extra = round(_as_money("BIZ_EXTRA_SEAT_USD", 3.0), 2)

    return dict(
        price_month=price_month,
        price_year=price_year,
        disc_pct=disc_pct,
        currency=currency,
        # 👇 claves que el billing.html usa explícitamente
        biz_price=biz_price,
        biz_included=biz_included,
        biz_extra=biz_extra,
    )

@router.get("/billing", response_class=HTMLResponse, include_in_schema=False)
def billing_page_alias(
    request: Request,
    db=Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    """
    Página principal de Facturación/Suscripción.
    Renderiza billing.html y el front hace fetch a /billing/me y /billing/history.
    """
    ctx = {"request": request, "user": user, "page_title": "Mi Suscripción | AlertTrail"}
    ctx.update(_pricing_ctx())
    return request.app.state.templates.TemplateResponse("billing.html", ctx)

@router.get("/account/billing", response_class=HTMLResponse, include_in_schema=False)
def billing_page_legacy(
    request: Request,
    db=Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    """
    Alias legacy para compatibilidad con rutas antiguas.
    """
    ctx = {"request": request, "user": user, "page_title": "Mi Suscripción | AlertTrail"}
    ctx.update(_pricing_ctx())
    return request.app.state.templates.TemplateResponse("billing.html", ctx)

# Algunos frontends aún navegan a /billing/subscriptions.
# Lo dejamos servido acá para que siempre use el mismo contexto correcto.
@router.get("/billing/subscriptions", response_class=HTMLResponse, include_in_schema=False)
def billing_subscriptions_alias(
    request: Request,
    db=Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    ctx = {"request": request, "user": user, "page_title": "Mi Suscripción | AlertTrail"}
    ctx.update(_pricing_ctx())
    return request.app.state.templates.TemplateResponse("billing.html", ctx)
