# app/routers/billing.py
from __future__ import annotations
import os
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.security import get_current_user_cookie_optional
from app.ui import templates
from app.i18n import get_lang, t

router = APIRouter(prefix="/billing", tags=["billing"])

def _env_float(name: str, default: float) -> float:
    try:
        v = os.getenv(name)
        if not v or "${{" in str(v): return float(default)
        return float(str(v).strip())
    except: return float(default)

def _env_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        if not v or "${{" in str(v): return int(default)
        return int(str(v).strip())
    except: return int(default)

def _get_val(obj, key, default=None):
    if isinstance(obj, dict): return obj.get(key, default)
    return getattr(obj, key, default)

@router.get("/subscriptions", response_class=HTMLResponse, include_in_schema=False)
def subscriptions(request: Request, user=Depends(get_current_user_cookie_optional)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)

    # Identificación de Plan y Roles
    current_plan = (_get_val(user, "plan") or "FREE").upper()
    is_admin = _get_val(user, "role") == "admin" or _get_val(user, "is_admin", False)
    is_pro = _get_val(user, "is_pro", False) or current_plan in ("PRO", "BIZ") or is_admin
    
    # Verificamos si ya usó la prueba gratuita alguna vez
    had_trial = bool(_get_val(user, "trial_used", False))
    trial_available = not is_pro and not had_trial

    # Configuración de Precios
    currency = os.getenv("BILLING_CURRENCY_SYMBOL", "USD")
    price_month = _env_float("PLAN_PRICE", 15.00) 
    disc_pct = _env_int("PRO_ANNUAL_DISTCOUNT_PCT", 20)
    price_year = round(price_month * 12 * (1 - (disc_pct / 100.0)), 2)

    # Configuración Plan Empresas (BIZ)
    biz_included = _env_int("BIZ_INCLUDED_SEATS", 25) 
    biz_extra = _env_float("BIZ_EXTRA_SET_USD", 3.00)
    biz_price = _env_float("BIZ_PRICE_MONTH_USD", 99.00)
    support_email = os.getenv("SUPPORT_EMAIL", "soporte@alerttrail.com")

    return templates.TemplateResponse(
        request=request,
        name="billing_subscriptions.html",
        context={
            "lang": lang, "t": t, "user": user,
            "current_plan": current_plan, 
            "is_pro": is_pro, 
            "is_admin": is_admin,
            "had_trial": had_trial, 
            "trial_available": trial_available,
            "currency": currency,
            "price_month": price_month, 
            "price_year": price_year, 
            "disc_pct": disc_pct,
            "biz_included": biz_included, 
            "biz_extra": biz_extra, 
            "biz_price": biz_price,
            "support_email": support_email
        }
    )

@router.get("/checkout", response_class=HTMLResponse, include_in_schema=False)
def checkout(request: Request, plan: str = "PRO", user=Depends(get_current_user_cookie_optional)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)
    plan = (plan or "PRO").upper().strip()
    plan_norm = "BIZ" if plan in ("BIZ", "BUSINESS", "EMPRESA", "EMPRESAS") else "PRO"

    support_email = os.getenv("SUPPORT_EMAIL", "soporte@alerttrail.com")

    # 🛑 ESTRATEGIA BIZ: Bloqueamos checkout automático y derivamos a venta consultiva
    if plan_norm == "BIZ":
        subject = "Consulta Plan Empresas - AlertTrail"
        body = "Hola equipo de AlertTrail,%0D%0A%0D%0AMe gustaría recibir más información sobre el despliegue corporativo del escáner para mi organización.%0D%0A%0D%0A"
        return RedirectResponse(url=f"mailto:{support_email}?subject={subject}&body={body}", status_code=303)

    # 🟢 ESTRATEGIA PRO: Calculamos si aplica el mes gratis
    had_trial = bool(_get_val(user, "trial_used", False))
    is_pro = _get_val(user, "is_pro", False) or (_get_val(user, "plan") or "FREE").upper() in ("PRO", "BIZ") or (_get_val(user, "role") == "admin")
    trial_available = not is_pro and not had_trial

    price = _env_float("PLAN_PRICE", 15.00)
    seats = 1
    extra = 0
    
    # Si tiene trial, le inyectamos la bandera a la URL de pagos para que la suscripción inicie desfasada
    trial_param = "&trial=30" if trial_available else ""
    init_point = f"/payments/pay?plan=PRO&seats=1{trial_param}"

    mp_enabled = bool(os.getenv("MP_ACCESS_TOKEN"))

    return templates.TemplateResponse(
        request=request,
        name="billing_checkout.html",
        context={
            "lang": lang, 
            "t": t, 
            "user": user,
            "plan": plan_norm, 
            "mp_enabled": mp_enabled,
            "init_point": init_point if mp_enabled else None,
            "currency_symbol": os.getenv("BILLING_CURRENCY_SYMBOL", "USD"),
            "price_month": price, 
            "included_seats": seats, 
            "extra_seat_price": extra,
            "trial_available": trial_available
        }
    )
