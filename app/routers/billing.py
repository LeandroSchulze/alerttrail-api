# app/routers/billing.py
import os
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from sqlalchemy.orm import Session

import mercadopago

from app.database import get_db
from app import models
from app.security import get_current_user_cookie

router = APIRouter(prefix="/billing", tags=["billing"])

# ======== ENV & helpers ========
BASE_URL = os.getenv("BASE_URL", "https://www.alerttrail.com").rstrip("/")
MP_ACCESS_TOKEN = (os.getenv("MP_ACCESS_TOKEN") or "").strip()

def _parse_float(v: Optional[str], default: float) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default

def _is_pro(u) -> bool:
    return bool(getattr(u, "is_pro", False)) or (getattr(u, "plan", "free") or "free").lower() == "pro"

def _set_plan(u: models.User, plan: str):
    p = (plan or "free").lower()
    if hasattr(u, "plan"):
        u.plan = p.upper() if p in ("free", "pro") else p
    if hasattr(u, "is_pro"):
        u.is_pro = (p == "pro")

def _sdk() -> mercadopago.SDK:
    if not MP_ACCESS_TOKEN:
        raise RuntimeError("Falta MP_ACCESS_TOKEN en variables de entorno")
    return mercadopago.SDK(MP_ACCESS_TOKEN)

def _compute_prices_for_ui() -> Tuple[str, float]:
    """
    Devuelve:
      display_label -> texto para el botón (ej: 'Mejorar a PRO (USD 10.00/mes · ~$5.999 ARS)')
      mp_amount_ars -> monto final que se envía a Mercado Pago (en ARS)
    Reglas:
      - Si PLAN_CURRENCY=USD: muestra USD y calcula ARS con USD_ARS,
        salvo que MP_PRICE_ARS (o PRO_PRICE_ARS) esté seteado (override).
      - Si PLAN_CURRENCY=ARS: muestra solo ARS (usa MP_PRICE_ARS o PLAN_PRICE).
    """
    currency = (os.getenv("PLAN_CURRENCY") or "USD").upper()
    price = _parse_float(os.getenv("PLAN_PRICE"), 10.0)

    # overrides (1) MP_PRICE_ARS, (2) PRO_PRICE_ARS (compat), (3) cálculo por USD_ARS
    override_mp = os.getenv("MP_PRICE_ARS")
    if override_mp is None:
        override_mp = os.getenv("PRO_PRICE_ARS")  # compatibilidad con versión anterior

    usd_ars = _parse_float(os.getenv("USD_ARS"), 600.0)

    if currency == "USD":
        if override_mp:
            mp_amount_ars = _parse_float(override_mp, round(price * usd_ars))
        else:
            mp_amount_ars = round(price * usd_ars)

        # Formato bonito con separador de miles estilo ES
        label = f"Mejorar a PRO (USD {price:.2f}/mes · ~${mp_amount_ars:,.0f} ARS)"
        label = label.replace(",", ".")  # 5,999 -> 5.999
        return label, float(mp_amount_ars)

    # currency == ARS
    if override_mp:
        mp_amount_ars = _parse_float(override_mp, price)
    else:
        mp_amount_ars = price

    label = f"Mejorar a PRO (${mp_amount_ars:,.0f}/mes)".replace(",", ".")
    return label, float(mp_amount_ars)

# ---------- UI ----------
@router.get("", response_class=HTMLResponse)
def billing_page(request: Request, current_user=Depends(get_current_user_cookie)):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)

    plan = (getattr(current_user, "plan", "FREE") or "FREE").upper()
    is_pro = _is_pro(current_user)
    display_label, _ = _compute_prices_for_ui()

    html = f"""
    <!doctype html><html lang="es"><meta charset="utf-8"><title>Plan | AlertTrail</title>
    <body style="font-family:system-ui;background:#0b2133;color:#e5f2ff;margin:0">
      <div style="max-width:900px;margin:40px auto;padding:0 16px">
        <a href="/dashboard" style="color:#93c5fd;text-decoration:none">&larr; Volver al dashboard</a>
        <h1 style="margin:16px 0 6px">Tu plan</h1>
        <div style="background:#0f2a42;border:1px solid #133954;border-radius:14px;padding:18px">
          <p style="margin:6px 0">Estado actual: <b>{plan}</b></p>
          <div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:10px">
            {(
              f'<form method="post" action="/billing/checkout"><button style="padding:10px 14px;border:0;border-radius:10px;background:#10b981;color:#06241f;font-weight:700;cursor:pointer">{display_label}</button></form>'
              if not is_pro else
              '<form method="post" action="/billing/downgrade"><button style="padding:10px 14px;border:0;border-radius:10px;background:#fbbf24;color:#3a2a00;font-weight:700;cursor:pointer">Bajar a FREE</button></form>'
            )}
          </div>
          <div style="margin-top:14px;color:#bcd7f0">
            <ul>
              <li>Pago vía Mercado Pago (Checkout Pro).</li>
              <li>Al aprobarse, tu cuenta pasa a PRO automáticamente.</li>
            </ul>
          </div>
        </div>
      </div>
    </body></html>
    """
    return HTMLResponse(html)

# ---------- Iniciar Checkout Pro ----------
@router.post("/checkout")
def checkout(request: Request, current_user=Depends(get_current_user_cookie)):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)

    _, mp_amount_ars = _compute_prices_for_ui()

    sdk = _sdk()
    pref = {
        "items": [{
            "title": "AlertTrail PRO - 1 mes",
            "quantity": 1,
            "unit_price": mp_amount_ars,   # Monto en ARS
            "currency_id": "ARS",
        }],
        "payer": {
            "email": getattr(current_user, "email", None),
        },
        "external_reference": f"user:{getattr(current_user, 'id', '')}",
        "back_urls": {
            "success": f"{BASE_URL}/billing/success",
            "failure": f"{BASE_URL}/billing/failure",
            "pending": f"{BASE_URL}/billing/pending",
        },
        "auto_return": "approved",
        "notification_url": f"{BASE_URL}/billing/ipn",  # webhook
    }

    resp = sdk.preference().create(pref)
    init_point = resp["response"].get("init_point") or resp["response"].get("sandbox_init_point")
    if not init_point:
        raise HTTPException(status_code=500, detail="No se pudo crear la preferencia de pago")
    return RedirectResponse(url=init_point, status_code=303)

# ---------- Webhook (IPN/Webhook de MP) ----------
@router.post("/ipn")
async def mp_ipn(request: Request, db: Session = Depends(get_db)):
    """
    Mercado Pago envía notificaciones aquí cuando cambia el estado del pago.
    Validamos consultando la API con el payment_id y activamos PRO si está 'approved'.
    """
    try:
        qp = request.query_params
        try:
            body = await request.json()
        except Exception:
            body = {}

        topic = qp.get("type") or (body.get("type") if isinstance(body, dict) else None)
        payment_id = qp.get("id") or ((body.get("data") or {}).get("id") if isinstance(body, dict) else None)

        # Solo pagos
        if str(topic).lower() != "payment" or not payment_id:
            return PlainTextResponse("ignored", status_code=200)

        sdk = _sdk()
        payment = sdk.payment().get(payment_id)
        pr = payment.get("response", {}) or {}
        status_mp = (pr.get("status") or "").lower()
        ext = pr.get("external_reference") or ""

        if status_mp == "approved" and ext.startswith("user:"):
            try:
                user_id = int(ext.split(":", 1)[1])
            except Exception:
                user_id = None
            if user_id:
                user = db.query(models.User).filter(models.User.id == user_id).first()
                if user:
                    _set_plan(user, "pro")
                    db.add(user)
                    db.commit()

        # Siempre 200; MP reintenta si no recibe 200
        return PlainTextResponse("ok", status_code=200)

    except Exception:
        # No devolvemos 500 para evitar reintentos infinitos
        return PlainTextResponse("ok", status_code=200)

# ---------- páginas de retorno ----------
@router.get("/success", response_class=HTMLResponse)
def success_page(request: Request, current_user=Depends(get_current_user_cookie)):
    return HTMLResponse(
        "<h2>¡Pago aprobado!</h2><p>Si tu plan aún no muestra PRO, refrescá en unos segundos.</p>"
        "<a href='/dashboard'>Volver al dashboard</a>"
    )

@router.get("/failure", response_class=HTMLResponse)
def failure_page(request: Request):
    return HTMLResponse("<h2>Pago rechazado o cancelado</h2><a href='/billing'>Volver a Plan</a>", status_code=400)

@router.get("/pending", response_class=HTMLResponse)
def pending_page(request: Request):
    return HTMLResponse("<h2>Pago pendiente</h2><p>Te avisaremos cuando se acredite.</p><a href='/dashboard'>Volver al dashboard</a>")

# ---------- baja manual ----------
@router.post("/downgrade")
def downgrade(current_user=Depends(get_current_user_cookie), db: Session = Depends(get_db)):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)
    user = db.query(models.User).filter(models.User.id == getattr(current_user, "id")).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    _set_plan(user, "free")
    db.add(user)
    db.commit()
    return RedirectResponse(url="/billing", status_code=303)
