# app/routers/billing_ui.py
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
import os
from decimal import Decimal

from app.security import get_current_user_cookie

router = APIRouter(prefix="/billing", tags=["billing"])

def _as_int(v, d):
    try: return int(v)
    except Exception:
        try: return int(float(v))
        except Exception: return d

def _as_money(v, d):
    try: return float(Decimal(str(v).replace(",", ".")))
    except Exception: return float(d)

def _pricing_ctx_from_env():
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

@router.get("/", response_class=HTMLResponse)
def billing_home(request: Request, user=Depends(get_current_user_cookie)):
    """
    FACTURACIÓN (estado, cambio de plan, historial)
    """
    ctx = {"request": request, "user": user, "page_title": "Facturación"}
    ctx.update(_pricing_ctx_from_env())
    return request.app.state.templates.TemplateResponse("billing.html", ctx)

@router.get("/subscriptions", response_class=HTMLResponse)
def billing_subscriptions(request: Request, user=Depends(get_current_user_cookie)):
    """
    SUSCRIPCIONES (gestión pura de la suscripción activa)
    """
    ctx = {"request": request, "user": user, "page_title": "Suscripciones"}
    ctx.update(_pricing_ctx_from_env())
    # usa un template distinto para que NO se vea igual que billing
    return request.app.state.templates.TemplateResponse("subscriptions.html", ctx)
