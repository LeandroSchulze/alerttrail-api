# app/routers/payments_mp.py
from __future__ import annotations

import os
import hmac
import json
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, Any

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, PaymentEvent, PaymentHistory
from app.mailer import send_payment_confirmation_email
from app.security import get_current_user_cookie
from app.routers.payments_history import _safe_currency
from app.services.mp_client import MPClient

MP_ACCESS_TOKEN = (os.getenv("MP_ACCESS_TOKEN") or "").strip()
MP_WEBHOOK_SECRET = (os.getenv("MP_WEBHOOK_SECRET") or "").strip()
APP_BASE_URL = (os.getenv("APP_BASE_URL") or "http://localhost:8000").rstrip("/")

router = APIRouter(prefix="/payments", tags=["payments-mp"])

# --------- Helpers ---------
def _resolve_user_by_email_or_id(db: Session, email: Optional[str], user_id: Optional[int]) -> Optional[User]:
    if user_id:
        u = db.query(User).get(user_id)
        if u:
            return u
    if email:
        return db.query(User).filter(User.email.ilike(email.strip().lower())).first()
    return None

def _pick_expiry_attr(user: User) -> str:
    """
    Devuelve el nombre del atributo datetime en el usuario donde se guarda la membresía PRO.
    Mantén esto alineado con tu modelo (e.g., 'pro_expires_at' o 'plan_pro_expires_at').
    """
    # Compatibilidad: intenta varios nombres comunes
    for candidate in ("pro_expires_at", "plan_pro_expires_at", "pro_until", "pro_expiry"):
        if hasattr(user, candidate):
            return candidate
    # Por defecto, crea el atributo 'pro_expires_at' si no existe.
    return "pro_expires_at"

def _extend_expiry(current: Optional[datetime], delta: timedelta) -> datetime:
    now = datetime.now(timezone.utc)
    base = current if (current and current > now) else now
    return base + delta

def _plan_to_delta(plan: str, period: str) -> timedelta:
    key = f"{plan}:{period}".lower()
    if key in ("pro:monthly", "pro:month"):
        return timedelta(days=31)
    if key in ("pro:yearly", "pro:annual", "pro:year"):
        return timedelta(days=366)
    # trial fallback
    if key in ("pro:trial", "trial:any"):
        return timedelta(days=5)
    # default monthly
    return timedelta(days=31)

def _amount_for(plan: str, period: str) -> Tuple[int, str, str]:
    """
    Devuelve (amount_in_cents, currency, description)
    Ajusta estos valores a tus precios reales.
    """
    plan = plan.lower()
    period = period.lower()
    if plan == "pro" and period in ("monthly", "month"):
        return (1000, "USD", "AlertTrail PRO - Monthly")
    if plan == "pro" and period in ("yearly", "annual", "year"):
        return (10000, "USD", "AlertTrail PRO - Yearly")
    if period == "trial":
        return (0, "USD", "AlertTrail PRO - Trial")
    # default
    return (1000, "USD", "AlertTrail PRO - Monthly")

def _safe_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except Exception:
        return None

def _store_event(db: Session, *, event_id: str, type_: str, data: dict, http_headers: dict) -> PaymentEvent:
    exists = db.query(PaymentEvent).filter(PaymentEvent.event_id == event_id).first()
    if exists:
        return exists
    ev = PaymentEvent(
        event_id=event_id,
        topic=type_,
        raw=data,
        headers=http_headers,
        processed_at=None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev

def _mark_event_processed(db: Session, ev: PaymentEvent):
    if not ev.processed_at:
        ev.processed_at = datetime.now(timezone.utc)
        db.add(ev)
        db.commit()

def _finalize_successful_payment(
    db: Session,
    *,
    user: User,
    payment: dict,
    plan: str,
    period: str,
    origin: str,
) -> PaymentHistory:
    # Actualizar expiración PRO
    attr = _pick_expiry_attr(user)
    current_expiry = getattr(user, attr, None)
    delta = _plan_to_delta(plan, period)
    new_expiry = _extend_expiry(current_expiry, delta)
    setattr(user, attr, new_expiry)
    setattr(user, "plan", "PRO") if hasattr(user, "plan") else None
    db.add(user)

    # Guardar PaymentHistory
    amount_cents = int(round(float(payment.get("transaction_amount", 0) or 0) * 100))
    currency = _safe_currency(payment.get("currency_id") or payment.get("currency") or "USD")
    status = payment.get("status") or "approved"
    description = payment.get("description") or f"AlertTrail {plan.upper()} - {period.title()}"
    payment_id = str(payment.get("id") or payment.get("payment_id") or "")
    external_reference = payment.get("external_reference")
    payer_email = (payment.get("payer") or {}).get("email")

    ph = PaymentHistory(
        user_id=user.id,
        payment_id=payment_id,
        provider="mercado_pago",
        status=status,
        amount_cents=amount_cents,
        currency=currency,
        description=description,
        plan=plan.upper(),
        period=period.lower(),
        external_reference=external_reference,
        payer_email=payer_email,
        origin=origin,
        created_at=datetime.now(timezone.utc),
        expires_at=new_expiry,
        raw=payment,
    )
    db.add(ph)
    db.commit()
    db.refresh(ph)

    # Notificación por email (best-effort)
    try:
        send_payment_confirmation_email(
            to_email=user.email,
            username=getattr(user, "name", user.email),
            plan=plan.upper(),
            period=period,
            amount_cents=amount_cents,
            currency=currency,
            new_expiry=new_expiry,
            payment_id=payment_id,
        )
    except Exception:
        pass

    return ph

# --------- Public routes ---------

@router.post("/webhook", include_in_schema=False)
async def mp_webhook(request: Request, db = Depends(get_db)):  # <- sin type hint en dep
    """
    Webhook de Mercado Pago (notificaciones).
    Verifica (opcionalmente) la firma y procesa payments aprobados.
    """
    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="MP_ACCESS_TOKEN no configurado")

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    headers = {k: v for k, v in request.headers.items()}
    # Almacenar evento temprano (idempotencia)
    event_id = str(payload.get("id") or payload.get("data", {}).get("id") or headers.get("x-request-id") or hashlib.sha256(raw_body).hexdigest())
    ev = _store_event(db, event_id=event_id, type_=payload.get("type") or payload.get("topic") or "unknown", data=payload, http_headers=headers)

    # Verificación de firma (si MP_WEBHOOK_SECRET está seteado)
    if MP_WEBHOOK_SECRET:
        try:
            sig_ok = MPClient.verify_webhook_signature(headers, raw_body, MP_WEBHOOK_SECRET)
            if not sig_ok:
                return JSONResponse({"ok": True, "skipped": "invalid_signature"}, status_code=202)
        except Exception:
            # Si falla la verificación, no rechazamos con 4xx para que MP reintente,
            # pero no procesamos.
            return JSONResponse({"ok": True, "skipped": "signature_check_error"}, status_code=202)

    # Parseo de tópico / tipo
    topic = (payload.get("type") or payload.get("topic") or "").lower()
    data_id = str(payload.get("data", {}).get("id") or payload.get("id") or "")

    client = MPClient(MP_ACCESS_TOKEN)

    # Procesar pago
    handled = False
    if topic in ("payment", "payments"):
        payment = client.get_payment(data_id) if data_id else None
        if payment and (payment.get("status") in ("approved", "authorized")):
            # Intentar resolver usuario
            payer_email = (payment.get("payer") or {}).get("email")
            ext_ref = payment.get("external_reference")
            user_id = _safe_int(ext_ref) if ext_ref else None
            user = _resolve_user_by_email_or_id(db, payer_email, user_id)
            if user:
                # Extraer plan/period si vienen en metadata
                meta = payment.get("metadata") or {}
                plan = (meta.get("plan") or "pro").lower()
                period = (meta.get("period") or "monthly").lower()
                _finalize_successful_payment(
                    db, user=user, payment=payment, plan=plan, period=period, origin="webhook"
                )
                _mark_event_processed(db, ev)
                handled = True
        else:
            handled = True  # guardamos el evento pero no hay acción

    elif topic in ("merchant_order", "merchant_orders"):
        # Algunas integraciones envían merchant_order -> contiene payments
        mo = client.get_merchant_order(data_id) if data_id else None
        if mo:
            # Tomar el primer payment aprobado
            pay_list = mo.get("payments") or []
            for p in pay_list:
                if p.get("status") in ("approved", "authorized"):
                    payer_email = p.get("payer", {}).get("email") or (mo.get("payer") or {}).get("email")
                    ext_ref = mo.get("external_reference")
                    user_id = _safe_int(ext_ref) if ext_ref else None
                    user = _resolve_user_by_email_or_id(db, payer_email, user_id)
                    if user:
                        meta = mo.get("metadata") or {}
                        plan = (meta.get("plan") or "pro").lower()
                        period = (meta.get("period") or "monthly").lower()
                        _finalize_successful_payment(
                            db, user=user, payment=p, plan=plan, period=period, origin="webhook_merchant_order"
                        )
                        _mark_event_processed(db, ev)
                        handled = True
                        break
        else:
            handled = True

    # Respuesta idempotente
    return JSONResponse({"ok": True, "handled": handled, "event_id": ev.event_id}, status_code=200)

@router.get("/checkout")
def start_checkout(
    plan: str = Query("pro", pattern="^(?i:pro)$", description="Solo PRO de momento"),
    period: str = Query("monthly", pattern="^(?i:monthly|yearly|trial)$"),
    db = Depends(get_db),                               # <- sin type hint en dep
    user = Depends(get_current_user_cookie),            # <- sin type hint en dep
):
    """
    Crea una preferencia de Mercado Pago y devuelve la URL de pago.
    """
    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="MP_ACCESS_TOKEN no configurado")

    amount_cents, currency, description = _amount_for(plan, period)
    if period.lower() == "trial":
        # Evita crear preferencia con monto 0: activa directamente el trial
        attr = _pick_expiry_attr(user)
        new_expiry = _extend_expiry(getattr(user, attr, None), _plan_to_delta(plan, period))
        setattr(user, attr, new_expiry)
        setattr(user, "plan", "PRO") if hasattr(user, "plan") else None
        db.add(user)
        db.commit()
        # Historial
        ph = PaymentHistory(
            user_id=user.id,
            payment_id=f"trial-{user.id}-{int(datetime.now(timezone.utc).timestamp())}",
            provider="internal",
            status="approved",
            amount_cents=0,
            currency=currency,
            description="Trial PRO Activado",
            plan="PRO",
            period="trial",
            external_reference=str(user.id),
            payer_email=user.email,
            origin="trial",
            created_at=datetime.now(timezone.utc),
            expires_at=new_expiry,
            raw={"note": "trial_activation"},
        )
        db.add(ph)
        db.commit()
        db.refresh(ph)
        return {"ok": True, "trial_activated": True, "expires_at": new_expiry.isoformat()}

    client = MPClient(MP_ACCESS_TOKEN)
    back_urls = {
        "success": f"{APP_BASE_URL}/payments/return?status=success",
        "failure": f"{APP_BASE_URL}/payments/return?status=failure",
        "pending": f"{APP_BASE_URL}/payments/return?status=pending",
    }
    pref = client.create_preference(
        title=description,
        unit_price=amount_cents / 100.0,
        currency=currency,
        quantity=1,
        external_reference=str(user.id),
        metadata={"plan": plan.lower(), "period": period.lower(), "user_id": user.id},
        back_urls=back_urls,
        auto_return="approved",
        payer={"email": user.email, "name": getattr(user, "name", user.email)},
        notification_url=f"{APP_BASE_URL}/payments/webhook",
    )
    if not pref:
        raise HTTPException(status_code=502, detail="No se pudo crear la preferencia de pago")
    init_url = pref.get("init_point") or pref.get("sandbox_init_point")
    return {"ok": True, "init_point": init_url, "preference_id": pref.get("id")}

@router.get("/return", include_in_schema=False)
def checkout_return(
    status: str = Query("success"),
    payment_id: Optional[str] = Query(None, alias="payment_id"),
    merchant_order_id: Optional[str] = Query(None, alias="merchant_order_id"),
):
    """
    Punto de retorno visual. En general, el alta real de PRO la hace el webhook,
    pero redirigimos al dashboard con un mensaje.
    """
    target = f"/dashboard?payment_status={status}"
    return RedirectResponse(url=target)
