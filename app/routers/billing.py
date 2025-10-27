import os
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from app.security import get_current_user_cookie

router = APIRouter(prefix="/billing", tags=["billing"])

# ------------------------
# Helpers seguros
# ------------------------
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

# ------------------------
# Constantes seguras
# ------------------------
PLAN_PRICE_CENTS = _as_int("PLAN_PRICE_CENTS", 1000)
PLAN_CURRENCY = (_as_str("PLAN_CURRENCY", "USD") or "USD").upper()
REQ_TIMEOUT = _as_int("MP_REQ_TIMEOUT_SEC", 25)

# ------------------------
# Contexto para template
# ------------------------
def _pricing_ctx():
    cents = PLAN_PRICE_CENTS
    price_month = round(cents / 100.0, 2)
    disc_pct = _as_int("PLAN_ANNUAL_DISCOUNT_PCT", 20)
    disc_pct = max(0, min(95, disc_pct))
    price_year = round(price_month * 12 * (1 - disc_pct / 100.0), 2)
    currency = PLAN_CURRENCY
    return dict(
        price_month=price_month,
        price_year=price_year,
        disc_pct=disc_pct,
        currency=currency,
    )

# ------------------------
# Rutas
# ------------------------

@router.get("/", response_class=HTMLResponse)
def billing_page(request: Request, user=Depends(get_current_user_cookie)):
    """
    Página principal de facturación.
    Renderiza billing.html con contexto de precios y usuario actual.
    """
    ctx = {"request": request, "user": user, **_pricing_ctx()}
    return request.app.state.templates.TemplateResponse("billing.html", ctx)


@router.get("/subscriptions", response_class=HTMLResponse)
def billing_subscriptions(request: Request, user=Depends(get_current_user_cookie)):
    """
    Página alias /billing/subscriptions para compatibilidad y enlaces directos.
    """
    ctx = {"request": request, "user": user, **_pricing_ctx()}
    return request.app.state.templates.TemplateResponse("billing.html", ctx)


@router.get("/me")
def billing_me(request: Request, user=Depends(get_current_user_cookie)):
    """
    Endpoint JSON para obtener el estado de suscripción del usuario.
    """
    return {
        "email": user["email"],
        "plan": getattr(user, "plan", "FREE"),
        "is_pro": getattr(user, "is_pro", False),
        "expires": getattr(user, "plan_expires", None),
    }


@router.get("/history")
def billing_history():
    """
    Placeholder para historial de pagos.
    """
    return JSONResponse({"ok": True, "history": []})
