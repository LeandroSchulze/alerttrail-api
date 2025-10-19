# app/routers/payments_mp.py
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional, Tuple

import httpx
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User  # ajustá import según tu estructura

# NOTA: mantenemos el prefijo /webhook para no romper integraciones actuales
router = APIRouter(prefix="/webhook", tags=["payments-mp"])

MP_ACCESS_TOKEN = (os.getenv("MP_ACCESS_TOKEN") or "").strip()

# -----------------------------
# Utils MP API
# -----------------------------
async def get_mp_payment(payment_id: str) -> dict:
    """
    Consulta el pago en MP para verificar estado real y datos asociados.
    """
    if not MP_ACCESS_TOKEN:
        raise RuntimeError("Falta MP_ACCESS_TOKEN")
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()


# -----------------------------
# Vinculación pago -> usuario
# -----------------------------
def _parse_external_reference(external_reference: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    """
    Intenta extraer user_id o email desde external_reference.
    Admite formatos:
      - 'user:<id>'
      - 'email:<correo>'
      - 'user:<id>:ts:<timestamp>'  (común para idempotencia)
    Devuelve (user_id, email)
    """
    if not external_reference:
        return (None, None)
    try:
        ref = external_reference.strip()
        parts = ref.split(":")
        if len(parts) >= 2:
            if parts[0] == "user":
                return (int(parts[1]), None)
            if parts[0] == "email":
                return (None, parts[1])
    except Exception:
        pass
    return (None, None)


def _resolve_user_by_email_or_id(db: Session, email: Optional[str], user_id: Optional[int]) -> Optional[User]:
    """
    Devuelve el usuario si lo encuentra por id o email (case-insensitive).
    """
    u = None
    if user_id:
        u = db.query(User).get(user_id)
        if u:
            return u
    if email:
        u = db.query(User).filter(User.email.ilike(email)).first()
    return u


# -----------------------------
# Activación PRO idempotente
# -----------------------------
def activate_pro_for_user(
    db: Session,
    *,
    user: User,
    months: int = 1,
    payment_id: Optional[str] = None,
) -> bool:
    """
    Activa/renueva PRO. Soporta distintos esquemas de columnas:
      - user.is_pro (bool)
      - user.plan (str) -> 'PRO'
      - user.plan_expires (datetime) o user.pro_until (datetime)
    Es idempotente a nivel de "extensión en base a la fecha actual".
    """
    now = datetime.utcnow()

    # Marca de plan
    if hasattr(user, "is_pro"):
        try:
            user.is_pro = True
        except Exception:
            pass

    if hasattr(user, "plan"):
        try:
            user.plan = "PRO"
        except Exception:
            pass

    # Expiración (plan_expires o pro_until)
    expiry_attr = None
    if hasattr(user, "plan_expires"):
        expiry_attr = "plan_expires"
    elif hasattr(user, "pro_until"):
        expiry_attr = "pro_until"

    if expiry_attr:
        current = getattr(user, expiry_attr, None)
        if current and isinstance(current, datetime) and current > now:
            base = current
        else:
            base = now
        new_expiry = base + timedelta(days=30 * months)
        try:
            setattr(user, expiry_attr, new_expiry)
        except Exception:
            pass

    # Si querés guardar el último payment_id:
    # if hasattr(user, "last_payment_id") and payment_id:
    #     try:
    #         user.last_payment_id = payment_id
    #     except Exception:
    #         pass

    db.add(user)
    db.commit()
    db.refresh(user)
    return True


# -----------------------------
# Webhook MP
# -----------------------------
@router.post("/mercadopago", response_class=JSONResponse)
async def mercadopago_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Webhook de Mercado Pago.
    - Acepta body (JSON) o query params (topic=payment&id=...).
    - Consulta la API de MP con Access Token para verificar el estado real.
    - Si 'approved', intenta vincular usuario (metadata.email / metadata.user_id / external_reference / payer.email).
    - Activa PRO de forma idempotente.
    - Devuelve 200 siempre para que MP no reintente innecesariamente (salvo error grave).
    """

    if not MP_ACCESS_TOKEN:
        # Respondemos 200 para no provocar reintentos infinitos, pero indicamos el problema.
        return JSONResponse({"ok": False, "reason": "MP_ACCESS_TOKEN no configurado"}, status_code=200)

    # 1) Parse del body/query
    try:
        body = await request.json()
    except Exception:
        body = {}

    payment_id: Optional[str] = None
    if isinstance(body, dict):
        data = body.get("data") or {}
        # Esquemas típicos: {"type": "payment", "data":{"id": "123"}}
        payment_id = (data.get("id") or data.get("payment", {}).get("id")) if isinstance(data, dict) else None

    # Fallback por query params
    if not payment_id:
        qp = request.query_params
        payment_id = qp.get("id") or qp.get("data.id")

    if not payment_id:
        # No cortamos con 400 para evitar reintentos; dejamos rastro.
        return JSONResponse({"ok": True, "skipped": "sin payment_id"}, status_code=200)

    # 2) Consulta a la API de MP para validar el pago
    try:
        payment = await get_mp_payment(str(payment_id))
    except httpx.HTTPError as e:
        # No devolvemos 4xx para evitar reintentos: registramos y confirmamos.
        return JSONResponse({"ok": False, "reason": f"Error consultando MP: {e!r}"}, status_code=200)

    status = (payment.get("status") or "").lower()  # 'approved' esperado para éxito
    metadata = payment.get("metadata") or {}
    payer = payment.get("payer") or {}

    # 3) Intentamos resolver usuario
    # Preferencias de vinculación:
    #  a) metadata.user_id (explícito)
    #  b) external_reference -> user:<id>  |  email:<addr>
    #  c) metadata.email
    #  d) payer.email (no siempre coincide con el email de tu app)
    raw_ext_ref = payment.get("external_reference")
    user_id_from_ext, email_from_ext = _parse_external_reference(raw_ext_ref)

    meta_user_id = metadata.get("user_id")
    if meta_user_id is not None:
        try:
            meta_user_id = int(meta_user_id)
        except Exception:
            meta_user_id = None

    email = metadata.get("email") or email_from_ext or payer.get("email")
    user_id = meta_user_id or user_id_from_ext

    user = _resolve_user_by_email_or_id(db, email=email, user_id=user_id)

    # 4) Activación si approved
    if status == "approved" and user:
        ok = activate_pro_for_user(db, user=user, months=1, payment_id=str(payment_id))
        return JSONResponse(
            {
                "ok": True,
                "approved": True,
                "user_id": user.id,
                "email": getattr(user, "email", None),
                "plan": getattr(user, "plan", None),
                "is_pro": getattr(user, "is_pro", None),
                "plan_expires": (
                    getattr(user, "plan_expires").isoformat()
                    if getattr(user, "plan_expires", None)
                    else getattr(user, "pro_until").isoformat()
                    if getattr(user, "pro_until", None)
                    else None
                ),
            },
            status_code=200,
        )

    # 5) Estados no aprobados o sin usuario
    return JSONResponse(
        {
            "ok": True,
            "approved": False,
            "status": status,
            "user_found": bool(user),
            "user_id": getattr(user, "id", None) if user else None,
            "email_tried": email,
            "external_reference": raw_ext_ref,
        },
        status_code=200,
    )
