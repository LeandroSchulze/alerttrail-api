# app/routers/webhooks.py
from __future__ import annotations

import os, json, hmac, hashlib, re
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.payments.mp_client import sdk
from app.services.subscription import activate_pro
from app.models import User  # para fallback si solo tenemos email

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET")  # opcional (HMAC compartido)
PLAN_PRO_DAYS = int(os.getenv("PLAN_PRO_DAYS", "30"))

# -----------------------------
# Helpers
# -----------------------------
def _ok(payload: dict) -> JSONResponse:
    return JSONResponse(payload, status_code=200)

def _parse_user_from_external_reference(ext_ref: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    """
    Intenta extraer user_id o email desde external_reference.
    Admite:
      - "user:<id>"
      - "email:<addr>"
      - "<id>" (solo números)
      - "user:<id>:ts:<timestamp>"
    Devuelve (user_id, email)
    """
    if not ext_ref:
        return (None, None)
    ref = str(ext_ref).strip()
    # user:<id>[:...]
    m = re.match(r"^user:(\d+)(:.*)?$", ref)
    if m:
        try:
            return (int(m.group(1)), None)
        except Exception:
            pass
    # email:<addr>
    m = re.match(r"^email:([^:]+)$", ref)
    if m:
        return (None, m.group(1).strip())
    # sólo números = user_id
    if ref.isdigit():
        try:
            return (int(ref), None)
        except Exception:
            pass
    return (None, None)

def _resolve_user(db: Session, user_id: Optional[int], email: Optional[str]) -> Optional[User]:
    """
    Resuelve el usuario por id o por email (case-insensitive).
    """
    if user_id:
        u = db.query(User).get(user_id)
        if u:
            return u
    if email:
        return db.query(User).filter(User.email.ilike(email)).first()
    return None

# -----------------------------
# Core webhook
# -----------------------------
@router.post("/mercadopago", response_class=JSONResponse)
async def mercadopago_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Webhook de Mercado Pago.
    - Verifica firma HMAC si MP_WEBHOOK_SECRET está configurado.
    - Soporta notificaciones con type/topic 'payment' o 'merchant_order', y el esquema por query (?topic=payment&id=...).
    - Obtiene el pago desde el SDK y, si está 'approved', activa PRO por PLAN_PRO_DAYS (idempotente en activate_pro).
    - Siempre responde 200 para evitar reintentos excesivos del lado de MP.
    """
    # 1) Leer cuerpo
    body_bytes = await request.body()
    try:
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        payload = {}

    # 2) (Opcional) Validar firma HMAC (compartida) si está configurada
    if MP_WEBHOOK_SECRET:
        signature = request.headers.get("x-signature")
        if not signature:
            return _ok({"status": "missing-signature"})
        expected = hmac.new(MP_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return _ok({"status": "invalid-signature"})

    # 3) Extraer tipo/id (body o query)
    ntype = payload.get("type") or payload.get("topic")  # algunos envían 'topic'
    data = payload.get("data", {}) or {}
    payment_id = data.get("id") or payload.get("resource")

    # Fallback por query (?topic=payment&id=XXXX)
    if not ntype:
        ntype = request.query_params.get("topic")
    if not payment_id:
        payment_id = request.query_params.get("id")

    # 4) Procesamiento principal
    if ntype in ("payment", "merchant_order"):
        if ntype == "payment" and payment_id:
            # Caso directo: ya tenemos payment_id
            try:
                mp_resp = sdk.payment().get(payment_id)  # dict con 'response'
            except Exception:
                return _ok({"status": "mp-api-error", "step": "payment.get"})

            resp = (mp_resp.get("response") or {})
            status = (resp.get("status") or "").lower()
            ext_ref = resp.get("external_reference")
            metadata = resp.get("metadata") or {}
            payer = resp.get("payer") or {}

            # Resolver usuario
            user_id_from_ext, email_from_ext = _parse_user_from_external_reference(ext_ref)

            # Preferencias: metadata.user_id > ext_ref user > metadata.email > payer.email
            meta_user_id = metadata.get("user_id")
            try:
                meta_user_id = int(meta_user_id) if meta_user_id is not None else None
            except Exception:
                meta_user_id = None

            email = metadata.get("email") or email_from_ext or payer.get("email")
            user = _resolve_user(db, user_id=(meta_user_id or user_id_from_ext), email=email)

            if status == "approved" and user:
                ok = activate_pro(db, user_id=user.id, payment_id=str(payment_id), days=PLAN_PRO_DAYS)
                return _ok({"status": "ok" if ok else "not-found", "user_id": user.id, "approved": True})

            return _ok({
                "status": "ignored-or-unlinked",
                "approved": (status == "approved"),
                "user_found": bool(user),
                "ext_ref": ext_ref,
                "email_candidate": email,
            })

        elif ntype == "merchant_order" and payment_id:
            # Algunas integraciones envían merchant_order: buscamos pagos aprobados dentro de la orden
            try:
                mo = sdk.merchant_order().get(payment_id)
            except Exception:
                return _ok({"status": "mp-api-error", "step": "merchant_order.get"})

            mo_resp = mo.get("response") or {}
            payments = mo_resp.get("payments") or []
            # Intentamos con el primer payment aprobado
            approved_pid = None
            for p in payments:
                if (p.get("status") or "").lower() == "approved":
                    approved_pid = p.get("id")
                    break

            if not approved_pid:
                return _ok({"status": "no-approved-payment-in-merchant-order"})

            # Re-uso del flujo de payment
            try:
                mp_resp = sdk.payment().get(approved_pid)
            except Exception:
                return _ok({"status": "mp-api-error", "step": "payment.get-from-order"})

            resp = (mp_resp.get("response") or {})
            status = (resp.get("status") or "").lower()
            ext_ref = resp.get("external_reference")
            metadata = resp.get("metadata") or {}
            payer = resp.get("payer") or {}

            user_id_from_ext, email_from_ext = _parse_user_from_external_reference(ext_ref)
            meta_user_id = metadata.get("user_id")
            try:
                meta_user_id = int(meta_user_id) if meta_user_id is not None else None
            except Exception:
                meta_user_id = None

            email = metadata.get("email") or email_from_ext or payer.get("email")
            user = _resolve_user(db, user_id=(meta_user_id or user_id_from_ext), email=email)

            if status == "approved" and user:
                ok = activate_pro(db, user_id=user.id, payment_id=str(approved_pid), days=PLAN_PRO_DAYS)
                return _ok({"status": "ok" if ok else "not-found", "user_id": user.id, "approved": True})

            return _ok({
                "status": "ignored-or-unlinked",
                "approved": (status == "approved"),
                "user_found": bool(user),
                "ext_ref": ext_ref,
                "email_candidate": email,
                "source": "merchant_order",
            })

    # Si no matchea nada relevante:
    return _ok({"status": "ignored"})
