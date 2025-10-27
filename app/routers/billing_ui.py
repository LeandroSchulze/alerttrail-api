import os
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.database import get_db
from app.security import get_current_user_cookie

router = APIRouter(tags=["billing-ui"])

def _pricing_ctx():
    cents = int(os.getenv("PLAN_PRICE_CENTS", "1000"))  # USD 10 por defecto
    price_month = round(cents / 100.0, 2)
    disc_pct = int(os.getenv("PLAN_ANNUAL_DISCOUNT_PCT", "20"))  # 20% por defecto
    price_year = round(price_month * 12 * (1 - disc_pct / 100), 2)
    currency = (os.getenv("PLAN_CURRENCY", "USD") or "USD").upper()
    return dict(
        price_month=price_month,
        price_year=price_year,
        disc_pct=disc_pct,
        currency=currency,
    )

@router.get("/billing", response_class=HTMLResponse, include_in_schema=False)
def billing_page_alias(
    request: Request,
    db=Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    ctx = {"request": request, "user": user, "page_title": "Mi Suscripción | AlertTrail"}
    ctx.update(_pricing_ctx())
    return request.app.state.templates.TemplateResponse("billing.html", ctx)

@router.get("/account/billing", response_class=HTMLResponse, include_in_schema=False)
def billing_page_legacy(
    request: Request,
    db=Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    ctx = {"request": request, "user": user, "page_title": "Mi Suscripción | AlertTrail"}
    ctx.update(_pricing_ctx())
    return request.app.state.templates.TemplateResponse("billing.html", ctx)
