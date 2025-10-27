# app/routers/billing.py
import os
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from app.security import get_current_user_cookie

router = APIRouter(prefix="/billing", tags=["billing"])

def _as_int(name: str, default: int) -> int:
    v = (os.getenv(name, "") or "").strip()
    try:
        return int(v.replace("_", "").replace(",", ""))
    except Exception:
        return int(default)

def _as_float(name: str, default: float) -> float:
    v = (os.getenv(name, "") or "").strip()
    v = v.replace("_", "").replace(" ", "").replace(",", ".")
    try:
        return float(v)
    except Exception:
        return float(default)

def _pricing_ctx():
    cents = _as_int("PLAN_PRICE_CENTS", 1000)
    price_month = round(cents / 100.0, 2)
    disc_pct = _as_int("PLAN_ANNUAL_DISCOUNT_PCT", 20)
    price_year = round(price_month * 12 * (1 - disc_pct / 100.0), 2)
    currency = (os.getenv("PLAN_CURRENCY", "USD") or "USD").upper()

    biz_price   = _as_float("BIZ_PRICE_MONTH_USD", 99.0)
    biz_included= _as_int("BIZ_INCLUDED_SEATS", 25)
    biz_extra   = _as_float("BIZ_EXTRA_SEAT_USD", 3.0)
    empresas_price = _as_float("EMPRESAS_PRICE_MONTH", 49.0)

    return dict(
        price_month=price_month, price_year=price_year, disc_pct=disc_pct, currency=currency,
        biz_price=biz_price, biz_included=biz_included, biz_extra=biz_extra, empresas_price=empresas_price
    )

@router.get("/", response_class=HTMLResponse)
def billing_page(request: Request, user=Depends(get_current_user_cookie)):
    ctx = {"request": request, "user": user}
    ctx.update(_pricing_ctx())
    return request.app.state.templates.TemplateResponse("billing.html", ctx)

@router.get("/subscriptions", response_class=HTMLResponse)
def billing_subscriptions(request: Request, user=Depends(get_current_user_cookie)):
    ctx = {"request": request, "user": user}
    ctx.update(_pricing_ctx())
    return request.app.state.templates.TemplateResponse("billing.html", ctx)

@router.get("/me")
def billing_me(user=Depends(get_current_user_cookie)):
    return {"email": user["email"], "plan": user.get("plan", "FREE"), "is_pro": bool(user.get("is_pro", False))}

@router.get("/history")
def billing_history():
    return JSONResponse({"ok": True, "history": []})
