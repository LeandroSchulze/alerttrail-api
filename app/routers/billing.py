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
BASE_URL = (os.getenv("BASE_URL") or "https://www.alerttrail.com").rstrip("/")
MP_ACCESS_TOKEN = (os.getenv("MP_ACCESS_TOKEN") or "").strip()


def _parse_float(v: Optional[str], default: float) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _is_pro(u) -> bool:
    return bool(getattr(u, "is_pro", False)) or (getattr(u, "plan", "free") or "free").lower() in {"pro", "biz"}


def _set_plan(u: models.User, plan: str):
    """Guarda 'PRO' o 'BIZ' (o 'FREE'). Marca is_pro=True para PRO o BIZ."""
    p = (plan or "free").lower()
    if hasattr(u, "plan"):
        u.plan = p.upper() if p in ("free", "pro", "biz") else p
    if hasattr(u, "is_pro"):
        u.is_pro = (p in {"pro", "biz"})


def _sdk() -> mercadopago.SDK:
    if not MP_ACCESS_TOKEN:
        raise RuntimeError("Falta MP_ACCESS_TOKEN en variables de entorno")
    return mercadopago.SDK(MP_ACCESS_TOKEN)


def _compute_price_pro() -> Tuple[str, float, str]:
    """
    PRO:
      - Label para UI
      - Monto ARS (para Mercado Pago)
      - Título de la preferencia
    """
    currency = (os.getenv("PLAN_CURRENCY") or "USD").upper()
    price = _parse_float(os.getenv("PLAN_PRICE"), 10.0)
    usd_ars = _parse_float(os.getenv("USD_ARS"), 600.0)

    # overrides PRO en ARS (prioridad)
    override_mp = os.getenv("MP_PRICE_ARS") or os.getenv("PRO_PRICE_ARS")

    if currency == "USD":
        mp_amount_ars = _parse_float(override_mp, round(price * usd_ars))
        label = f"Mejorar a PRO (USD {price:.2f}/mes · ~${mp_amount_ars:,.0f} ARS)".replace(",", ".")
    else:
        mp_amount_ars = _parse_float(override_mp, price)
        label = f"Mejorar a PRO (${mp_amount_ars:,.0f}/mes)".replace(",", ".")

    title = "AlertTrail PRO - 1 mes"
    return label, float(mp_amount_ars), title


def _compute_price_biz() -> Tuple[str, float, str, int, float, float]:
    """
    BIZ/EMPRESAS:
      - Label para UI
      - Monto ARS (para Mercado Pago)
      - Título de la preferencia
      - Asientos incluidos
      - Precio extra seat USD y ARS (para mostrar en UI)
    """
    seats = int(os.getenv("BIZ_INCLUDED_SEATS") or 25)

    currency = (os.getenv("PLAN_CURRENCY") or "USD").upper()
    price_usd = _parse_float(os.getenv("BIZ_PRICE_USD"), 99.0)
    usd_ars = _parse_float(os.getenv("USD_ARS"), 600.0)

    # extra seat
    extra_usd = _parse_float(os.getenv("BIZ_EXTRA_SEAT_USD"), 3.0)
    extra_ars_override = os.getenv("BIZ_EXTRA_SEAT_ARS")

    # override total ARS para el abono BIZ
    override_biz_ars = os.getenv("BIZ_PRICE_ARS")

    if currency == "USD":
        mp_amount_ars = _parse_float(override_biz_ars, round(price_usd * usd_ars))
        extra_ars = _parse_float(extra_ars_override, round(extra_usd * usd_ars))
        label = (
            f"Plan EMPRESAS (USD {price_usd:.2f}/mes · ~${mp_amount_ars:,.0f} ARS · {seats} asientos, "
            f"adicional USD {extra_usd:.2f}/asiento)".replace(",", ".")
        )
    else:
        # Si quisieras soportar PLAN_CURRENCY=ARS directamente
        base_ars = _parse_float(os.getenv("PLAN_PRICE"), price_usd * usd_ars)
        mp_amount_ars = _parse_float(override_biz_ars, base_ars)
        extra_ars = _parse_float(extra_ars_override, round(extra_usd * usd_ars))
        label = (
            f"Plan EMPRESAS (${mp_amount_ars:,.0f}/mes · {seats} asientos, "
            f"adicional ~${extra_ars:,.0f}/asiento)".replace(",", ".")
        )

    title = "AlertTrail EMPRESAS - 1 mes"
    return label, float(mp_amount_ars), title, seats, float(extra_usd), float(extra_ars)


# ---------- UI ----------
@router.get("", response_class=HTMLResponse)
def billing_page(request: Request, current_user=Depends(get_current_user_cookie)):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)

    plan = (getattr(current_user, "plan", "FREE") or "FREE").upper()
    is_pro = _is_pro(current_user)

    pro_label, _, _ = _compute_price_pro()
    biz_label, _, _, seats, extra_usd, extra_ars = _compute_price_biz()

    html = f"""
    <!doctype html><html lang="es"><meta charset="utf-8"><title>Plan | AlertTrail</title>
    <body style="font-family:system-ui;background:#0b2133;color:#e5f2ff;margin:0">
      <div style="max-width:980px;margin:40px auto;padding:0 16px">
        <a href="/dashboard" style="color:#93c5fd;text-decoration:none">&larr; Volver al dashboard</a>
        <h1 style="margin:16px 0 6px">Tu plan</h1>

        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-top:12px">
          <div style="background:#0f2a42;border:1px solid #133954;border-radius:14px;padding:18px">
            <h2 style="margin:0 0 8px">FREE</h2>
            <p style="margin:6px 0">Estado actual: <b>{plan}</b></p>
            <p style='margin:6px 0;color:#bcd7f0'>Funciones básicas.</p>
            {"<form method='post' action='/billing/downgrade'><button style='padding:10px 14px;border:0;border-radius:10px;background:#fbbf24;color:#3a2a00;font-weight:700;cursor:pointer'>Bajar a FREE</button></form>" if is_pro else ""}
          </div>

          <div style="background:#0f2a42;border:1px solid #133954;border-radius:14px;padding:18px">
            <h2 style="margin:0 0 8px">PRO</h2>
            <ul style="color:#bcd7f0;margin:6px 0 12px">
              <li>Funciones avanzadas</li>
              <li>Integraciones clave</li>
            </ul>
            <div style="display:flex;gap:10px;flex-wrap:wrap">
              <form method="post" action="/billing/checkout?plan=PRO">
                <button style="padding:10px 14px;border:0;border-radius:10px;background:#10b981;color:#06241f;font-weight:700;cursor:pointer">{pro_label}</button>
              </form>
            </div>
          </div>

          <div style="background:#0f2a42;border:1px solid #133954;border-radius:14px;padding:18px">
            <h2 style="margin:0 0 8px">EMPRESAS</h2>
            <ul style="color:#bcd7f0;margin:6px 0 12px">
              <li>Todo PRO + capacidades de equipo</li>
              <li><b>{seats}</b> asientos incluidos</li>
              <li>Asiento adicional: <b>USD {extra_usd:.2f}</b> (~${extra_ars:,.0f} ARS)</li>
            </ul>
            <div style="display:flex;gap:10px;flex-wrap:wrap">
              <form method="post" action="/billing/checkout?plan=BIZ">
                <button style="padding:10px 14px;border:0;border-radius:10px;background:#0ea5e9;color:#03131c;font-weight:700;cursor:pointer">{biz_label}</button>
              </form>
            </div>
          </div>
        </div>
      </div>
    </body></html>
    """
    return HTMLResponse(html)


# ---------- Iniciar Checkout Pro / Empresas ----------
@router.api_route("/checkout", methods=["GET", "POST"])
def checkout(request: Request, current_user=Depends(get_current_user_cookie)):
    """
    Acepta GET y POST. Usa query param ?plan=PRO|BIZ (default PRO).
    """
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)

    plan = (request.query_params.get("plan") or "PRO").upper()
    if plan not in {"PRO", "BIZ"}:
        plan = "PRO"

    if plan == "PRO":
        _, mp_amount_ars, title = _compute_price_pro()
    else:
        _, mp_amount_ars, title, _, _, _ = _compute_price_biz()

    sdk = _sdk()
    pref = {
        "items": [{
            "title": title,
            "quantity": 1,
            "unit_price": mp_amount_ars,   # Monto en ARS
            "currency_id": "ARS",
        }],
        "payer": {
            "email": getattr(current_user, "email", None),
        },
        # Mandamos el plan en external_reference
        "external_reference": f"user:{getattr(current_user, 'id', '')}:plan:{plan}",
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
    Validamos consultando la API con el payment_id y activamos PRO/BIZ si está 'approved'.
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
            # form: user:<id>:plan:<PRO|BIZ>
            user_id: Optional[int] = None
            plan = "PRO"
            try:
                parts = ext.split(":")
                if len(parts) >= 4:
                    user_id = int(parts[1])
                    plan = parts[3].upper()
            except Exception:
                pass

            if user_id:
                user = db.query(models.User).filter(models.User.id == user_id).first()
                if user:
                    _set_plan(user, "BIZ" if plan == "BIZ" else "PRO")
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
        "<h2>¡Pago aprobado!</h2><p>Si tu plan aún no muestra el cambio, refrescá en unos segundos.</p>"
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
