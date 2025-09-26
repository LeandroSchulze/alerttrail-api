# app/routers/payments.py
import os
import json
import uuid
from typing import Optional

import requests
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..security import get_current_user_cookie

router = APIRouter(tags=["payments"])

# =========================
# Configuración / Precios
# =========================
MP_ACCESS_TOKEN = (os.getenv("MP_ACCESS_TOKEN") or "").strip()
BASE_URL = os.getenv("BASE_URL", "https://www.alerttrail.com").rstrip("/")

# Precios base (USD)
PRO_PRICE_USD = float(os.getenv("PRO_PRICE_USD", "10"))
BIZ_PRICE_USD = float(os.getenv("BIZ_PRICE_USD", "99"))
BIZ_INCLUDED_SEATS = int(os.getenv("BIZ_INCLUDED_SEATS", "3"))
BIZ_EXTRA_SEAT_USD = float(os.getenv("BIZ_EXTRA_SEAT_USD", "3"))

# Conversión opcional a ARS
USD_ARS = float(os.getenv("USD_ARS", "0"))  # si es 0, se cobra en USD

# Frecuencia de cobro (mensual)
RECUR_FREQ = 1
RECUR_FREQ_TYPE = "months"  # "months" según API de MP

# ============================================
# Modelo local de suscripciones (tabla simple)
# ============================================
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base

SubBase = declarative_base()
_engine = SessionLocal().get_bind() if hasattr(SessionLocal, "get_bind") else SessionLocal().bind

class Subscription(SubBase):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("preapproval_id", name="uq_preapproval_id"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    preapproval_id = Column(String, unique=True, index=True)
    status = Column(String, index=True)  # authorized/paused/cancelled/pending
    plan = Column(String)  # PRO / BIZ
    seats = Column(Integer, default=1)
    currency = Column(String, default="USD")
    amount = Column(Integer)  # monto por periodo (entero por simplicidad)
    next_payment_date = Column(String)
    external_reference = Column(String, index=True)
    raw = Column(Text)  # JSON crudo de MP
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

# Crear tabla si no existe
try:
    SubBase.metadata.create_all(bind=_engine)
except Exception:
    # En algunos entornos de build no hay DB lista; se creará en runtime del webservice.
    pass


# =========================
# Helpers de precios/MP
# =========================
def _require_mp_token():
    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="MP_ACCESS_TOKEN no configurado en el entorno")

def _calc_biz_amount_usd(seats: int) -> float:
    seats = max(1, int(seats or 1))
    extra = max(0, seats - BIZ_INCLUDED_SEATS)
    return BIZ_PRICE_USD + extra * BIZ_EXTRA_SEAT_USD

def _amount_currency(plan: str, seats: Optional[int] = None):
    """
    Retorna (amount, currency) para MP auto_recurring.
    Si USD_ARS > 0 => cobra en ARS con conversión simple.
    """
    plan = (plan or "PRO").upper()
    if plan == "BIZ":
        usd = _calc_biz_amount_usd(seats or 1)
    else:
        usd = PRO_PRICE_USD

    if USD_ARS > 0:
        return round(usd * USD_ARS, 2), "ARS"
    return round(usd, 2), "USD"

def _preapproval_payload(payer_email: str, amount: float, currency: str, reason: str, external_ref: str):
    """
    Payload recomendado por Mercado Pago para crear un preapproval (débito automático).
    """
    return {
        "reason": reason,
        "auto_recurring": {
            "frequency": RECUR_FREQ,
            "frequency_type": RECUR_FREQ_TYPE,
            "transaction_amount": amount,
            "currency_id": currency
        },
        "back_url": f"{BASE_URL}/billing/return",
        "payer_email": payer_email,
        "external_reference": external_ref
    }

def _mp_headers():
    return {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

def _mp_get_preapproval(preapproval_id: str):
    url = f"https://api.mercadopago.com/preapproval/{preapproval_id}"
    r = requests.get(url, headers=_mp_headers(), timeout=20)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"MP GET preapproval error {r.status_code}: {r.text}")
    return r.json()


# =========================
# Endpoints
# =========================
@router.get("/payments/subscribe", response_class=RedirectResponse)
def payments_subscribe(
    request: Request,
    plan: str = Query(..., regex="^(?i)(PRO|BIZ)$"),
    seats: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    """
    Crea un preapproval en MP y redirige a la URL de autorización del cliente.
    - plan: PRO o BIZ
    - seats: usado sólo para BIZ (asientos totales); los extras se cobran a BIZ_EXTRA_SEAT_USD.
    """
    _require_mp_token()
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    plan_norm = plan.upper()
    amount, currency = _amount_currency(plan_norm, seats)
    external_ref = f"sub-{plan_norm}-{user.id}-{uuid.uuid4().hex[:8]}"
    reason = f"AlertTrail {plan_norm} ({currency} {amount})"

    payload = _preapproval_payload(payer_email=user.email, amount=amount, currency=currency,
                                   reason=reason, external_ref=external_ref)
    url = "https://api.mercadopago.com/preapproval"
    r = requests.post(url, headers=_mp_headers(), data=json.dumps(payload), timeout=25)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"MP preapproval error {r.status_code}: {r.text}")

    data = r.json()
    preapproval_id = data.get("id")
    init_point = data.get("init_point") or data.get("sandbox_init_point")

    # Guardar/actualizar suscripción local
    sub = Subscription(
        user_id=user.id,
        preapproval_id=preapproval_id,
        status=data.get("status") or "pending",
        plan=plan_norm,
        seats=seats if plan_norm == "BIZ" else 1,
        currency=currency,
        amount=int(round(amount)),   # entero simple; si querés, guarda con 2 decimales en string
        next_payment_date=(data.get("auto_recurring") or {}).get("next_payment_date") or "",
        external_reference=external_ref,
        raw=json.dumps(data, ensure_ascii=False)
    )
    try:
        # upsert básico por preapproval_id
        exists = db.query(Subscription).filter(Subscription.preapproval_id == preapproval_id).first()
        if exists:
            exists.status = sub.status
            exists.plan = sub.plan
            exists.seats = sub.seats
            exists.currency = sub.currency
            exists.amount = sub.amount
            exists.next_payment_date = sub.next_payment_date
            exists.external_reference = sub.external_reference
            exists.raw = sub.raw
            exists.updated_at = datetime.now(timezone.utc)
        else:
            db.add(sub)
        db.commit()
    except Exception:
        db.rollback()
        # seguimos igual; el usuario igual podrá autorizar en MP

    if not init_point:
        # fallback: enviar a la página de retorno con un mensaje simple
        return RedirectResponse(url=f"{BASE_URL}/billing/return")

    return RedirectResponse(url=init_point)


@router.post("/payments/webhook")
def payments_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Webhook de Mercado Pago. MP envía cambios de estado de preapproval.
    Actualizamos la suscripción y, si está 'authorized', ponemos el plan del usuario.
    """
    _require_mp_token()
    try:
        # MP puede enviar JSON o query-params con id/type
        body = {}
        try:
            body = request.json()
        except Exception:
            pass

        # Render/Starlette: request.json() es async; manejarlo:
        if callable(getattr(body, "__await__", None)):
            body = request._body if hasattr(request, "_body") else {}

        # Si no logramos body por sync, probamos async de forma segura:
        # (en FastAPI, lo correcto sería: body = await request.json(), pero aquí somos sync)
    except Exception:
        body = {}

    # Soportar tanto JSON como query params
    params = dict(request.query_params)
    preapproval_id = params.get("id") or (body.get("data", {}) if isinstance(body, dict) else {}).get("id")
    topic = params.get("type") or params.get("topic") or body.get("type") if isinstance(body, dict) else None

    # Cuando el topic es 'preapproval', consultamos el detalle
    if preapproval_id:
        try:
            detail = _mp_get_preapproval(preapproval_id)
        except HTTPException as e:
            # Devolvemos 200 igualmente para que MP no reintente infinito
            return {"ok": False, "ignored": True, "reason": str(e.detail)}

        status_mp = (detail.get("status") or "").lower()  # authorized / paused / cancelled / pending
        ext_ref = detail.get("external_reference") or ""
        next_payment_date = (detail.get("auto_recurring") or {}).get("next_payment_date") or ""

        # Actualizar sub local
        sub = db.query(Subscription).filter(Subscription.preapproval_id == preapproval_id).first()
        if not sub:
            # Intento de localizar por external_reference
            sub = db.query(Subscription).filter(Subscription.external_reference == ext_ref).first()

        if sub:
            sub.status = status_mp
            sub.next_payment_date = next_payment_date
            sub.raw = json.dumps(detail, ensure_ascii=False)
            sub.updated_at = datetime.now(timezone.utc)
            try:
                db.commit()
            except Exception:
                db.rollback()

            # Si está authorized, activar plan al usuario
            if status_mp == "authorized" and sub.user_id:
                try:
                    from ..models import User
                    u = db.query(User).get(sub.user_id)
                    if u:
                        u.plan = sub.plan  # PRO o BIZ
                        db.commit()
                except Exception:
                    db.rollback()

        return {"ok": True, "status": status_mp, "preapproval_id": preapproval_id}

    # Si no hay id, no sabemos qué actualizar
    return {"ok": False, "ignored": True, "reason": "sin id"}


@router.get("/payments/status", response_class=JSONResponse)
def payments_status(
    preapproval_id: str = Query(...),
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    """
    Consulta el estado de una suscripción por su preapproval_id y sincroniza localmente.
    """
    _require_mp_token()
    detail = _mp_get_preapproval(preapproval_id)
    status_mp = (detail.get("status") or "").lower()
    next_payment_date = (detail.get("auto_recurring") or {}).get("next_payment_date") or ""

    sub = db.query(Subscription).filter(Subscription.preapproval_id == preapproval_id).first()
    if sub:
        sub.status = status_mp
        sub.next_payment_date = next_payment_date
        sub.raw = json.dumps(detail, ensure_ascii=False)
        sub.updated_at = datetime.now(timezone.utc)
        try:
            db.commit()
        except Exception:
            db.rollback()

        # también activamos plan si aplica
        if status_mp == "authorized" and sub.user_id:
            try:
                from ..models import User
                u = db.query(User).get(sub.user_id)
                if u:
                    u.plan = sub.plan
                    db.commit()
            except Exception:
                db.rollback()

    return {"ok": True, "status": status_mp, "next_payment_date": next_payment_date}


@router.post("/payments/cancel", response_class=JSONResponse)
def payments_cancel(
    preapproval_id: str = Query(...),
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    """
    Cancela/pausa una suscripción en MP. (Depende de permisos de la cuenta de MP)
    """
    _require_mp_token()
    # (nota: algunas cuentas usan PATCH /preapproval/{id} status=paused/cancelled)
    url = f"https://api.mercadopago.com/preapproval/{preapproval_id}"
    payload = {"status": "paused"}
    r = requests.put(url, headers=_mp_headers(), data=json.dumps(payload), timeout=20)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"MP cancel error {r.status_code}: {r.text}")

    detail = r.json()
    status_mp = (detail.get("status") or "").lower()

    # Actualizar local
    sub = db.query(Subscription).filter(Subscription.preapproval_id == preapproval_id).first()
    if sub:
        sub.status = status_mp
        sub.raw = json.dumps(detail, ensure_ascii=False)
        sub.updated_at = datetime.now(timezone.utc)
        try:
            db.commit()
        except Exception:
            db.rollback()

    return {"ok": True, "status": status_mp}


@router.get("/billing/return", response_class=HTMLResponse)
def billing_return():
    """
    Página de retorno para el usuario luego de autorizar en Mercado Pago.
    """
    html = """
    <h1>Suscripción AlertTrail</h1>
    <p>Si autorizaste el débito automático, tu plan quedará activo en minutos.
    Podés volver al <a href="/dashboard">dashboard</a> o revisar <a href="/billing/status">tu estado de suscripción</a>.</p>
    """
    return HTMLResponse(html)
