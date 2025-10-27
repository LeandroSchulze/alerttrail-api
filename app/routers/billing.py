# app/routers/billing.py
import os
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from app.security import get_current_user_cookie

router = APIRouter(prefix="/billing", tags=["billing"])

# Helpers robustos para ENV
def _as_int(env_name: str, default: int) -> int:
    v = (os.getenv(env_name, "") or "").strip()
    try:
        v = v.replace("_", "")
        return int(v)
    except Exception:
        return int(default)

def _as_str(env_name: str, default: str) -> str:
    v = (os.getenv(env_name) or default)
    return (v or default).strip()

PLAN_PRICE_CENTS = _as_int("PLAN_PRICE_CENTS", 1000)          # 1000 = USD 10
PLAN_CURRENCY    = (_as_str("PLAN_CURRENCY", "USD") or "USD").upper()
REQ_TIMEOUT      = _as_int("MP_REQ_TIMEOUT_SEC", 25)

def _pricing_ctx():
    cents = PLAN_PRICE_CENTS
    price_month = round(cents / 100.0, 2)
    disc_pct = _as_int("PLAN_ANNUAL_DISCOUNT_PCT", 20)
    disc_pct = max(0, min(95, disc_pct))
    price_year = round(price_month * 12 * (1 - disc_pct/100.0), 2)
    currency = PLAN_CURRENCY
    return dict(price_month=price_month, price_year=price_year, disc_pct=disc_pct, currency=currency)

@router.get("/", response_class=HTMLResponse)
def billing_page(request: Request, user=Depends(get_current_user_cookie)):
    ctx = {"request": request, "user": user, **_pricing_ctx()}
    return request.app.state.templates.TemplateResponse("billing.html", ctx)

@router.get("/subscriptions", response_class=HTMLResponse)
def billing_subscriptions(request: Request, user=Depends(get_current_user_cookie)):
    ctx = {"request": request, "user": user, **_pricing_ctx()}
    return request.app.state.templates.TemplateResponse("billing.html", ctx)

@router.get("/me")
def billing_me(user=Depends(get_current_user_cookie)):
    return {"email": user["email"], "plan": user.get("plan", "FREE"), "is_pro": bool(user.get("is_pro", False))}

@router.get("/history")
def billing_history():
    return JSONResponse({"ok": True, "history": []})
