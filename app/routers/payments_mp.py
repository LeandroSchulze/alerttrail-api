# app/routers/payments_mp.py
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import httpx
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

MP_ACCESS_TOKEN = (os.getenv("MP_ACCESS_TOKEN") or "").strip()
router = APIRouter(prefix="/webhook", tags=["payments-mp"])

# -----------------------------
# Helpers
# -----------------------------
def _resolve_user_by_email_or_id(db: Session, email: Optional[str], user_id: Optional[int]) -> Optional[User]:
    """Busca usuario por id o email (case-insensitive)."""
    if user_id:
        u = db.query(User).get(user_id)
        if u:
            return u
    if email:
        return db.query(User).filter(User.email.ilike(email)).first()
    return None

def _pick_expiry_attr(user: User) -> Optional[str]:
    """Devuelve el nombre del atributo de expiración que exista en el modelo."""
    for attr in ("pro_expires_at", "plan_expires", "pro_until"):
        if hasattr(user, attr):
            return attr
    return None

def activate_pro_for_user(db: Session, *, user: User, months: int = 1, payment_id: Optional[str] = None) -> bool:
    """Activa/Extiende PRO de forma idempotente."""
    now = datetime.now(timezone.utc)

    # Marca de plan
    try:
        if hasattr(user, "plan"):
            user.plan = "PRO"
        if hasattr(user, "is_pro"):
            user.is_pro = True
    except Exception:
        pass

    # Expiración
    expiry_attr = _pick_expiry_attr(user)
    if expiry_attr:
        current = getattr(user, expiry_attr, None)
        base = current if (isinstance(current, datetime) and current > now) else now
        new_expiry = base + timedelta(days=30 * months)
        try:
            setattr(user, expiry_attr, new_expiry)
        except Exception:
            pass

    # Idempotencia simple por último pago
    if hasattr(user, "last_payment_id") and payment_id:
        try:
            user.last_payment_id = str(payment_id)
        except Exception:
            pass

    db.add(user)
    db.commit()
    db.refresh(user)
    return True

async def _mp_get_payment(payment_id: str) -> Tuple[Optional[dict], Optional[str]]:
    """Consulta a MP por el pago; devuelve (json, error)."""
    if not MP_ACCESS_TOKEN:
        return None, "missing_token"
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, headers=headers)
    if r.status_code != 200:
        return None, f"http_{r.status_code}"
    try:
        return r.json(), None
    except Exception as e:
        return None, f"json_error:{e!r}"

# -----------------------------
# Webhook MP
# -----------------------------
@router.get("/mercadopago", response_class=JSONResponse)
async def mp_challenge():
    # MP suele hacer un GET “challenge” inicial
    return JSONResponse({"ok": True, "method": "GET"})

@router.post("/mercadopago", response_class=JSONResponse)
async def mp_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Webhook de Mercado Pago.
    - Valida pago con la API si viene payment_id.
    - Extrae user_id desde `external_reference` (número) o `metadata.user_id`/email.
    - Activa PRO de forma idempotente.
    - Devuelve 200 (incluso en algunos errores recuperables) para evitar reintentos excesivos.
    """
    # 1) Parse body
    try:
        body = await request.json()
    except Exception:
        body = {}

    # 2) Toma payment_id si viene
    payment_id = None
    if isinstance(body, dict):
        payment_id = (
            body.get("id")
            or body.get("data", {}).get("id")
            or body.get("resource")  # a veces viene URL completa
        )
        if isinstance(payment_id, str) and payment_id.startswith("https"):
            # /v1/payments/<id>
            payment_id = payment_id.rstrip("/").split("/")[-1]

    user: Optional[User] = None
    status: Optional[str] = None
    email: Optional[str] = None
    raw_ext_ref: Optional[str] = None

    # 3) Si hay payment_id y token, valida contra MP
    if payment_id and MP_ACCESS_TOKEN:
        pj, perr = await _mp_get_payment(str(payment_id))
        if pj:
            status = pj.get("status")
            raw_ext_ref = pj.get("external_reference")
            email = (pj.get("payer") or {}).get("email")
            # Prioridad: external_reference (num) > metadata.user_id > email
            user_id = None
            if raw_ext_ref and str(raw_ext_ref).isdigit():
                user_id = int(raw_ext_ref)
            elif isinstance(pj.get("metadata"), dict):
                mid = pj["metadata"].get("user_id") or pj["metadata"].get("uid")
                if mid and str(mid).isdigit():
                    user_id = int(mid)
            user = _resolve_user_by_email_or_id(db, email=email, user_id=user_id)

            if status == "approved" and user:
                activate_pro_for_user(db, user=user, months=1, payment_id=str(payment_id))
                # Arma respuesta con expiración real
                expiry_attr = _pick_expiry_attr(user)
                exp_val = getattr(user, expiry_attr) if (expiry_attr and hasattr(user, expiry_attr)) else None
                return JSONResponse({
                    "ok": True,
                    "approved": True,
                    "status": status,
                    "user_id": user.id,
                    "plan": getattr(user, "plan", None),
                    "expires_attr": expiry_attr,
                    "expires_at": exp_val.isoformat() if isinstance(exp_val, datetime) else None,
                    "last_payment_id": getattr(user, "last_payment_id", None),
                }, status_code=200)

    # 4) Fallback SIN validación (solo si no hay token/ID, para sandbox o pruebas)
    #    Usa external_reference o metadata del body crudo
    if not user:
        raw_ext_ref = raw_ext_ref or body.get("external_reference") or body.get("data", {}).get("external_reference")
        meta = body.get("metadata") or body.get("data", {}).get("metadata") or {}
        email = email or meta.get("email")
        user_id = None
        if raw_ext_ref and str(raw_ext_ref).isdigit():
            user_id = int(raw_ext_ref)
        else:
            mid = meta.get("user_id") or meta.get("uid")
            if mid and str(mid).isdigit():
                user_id = int(mid)
        user = _resolve_user_by_email_or_id(db, email=email, user_id=user_id)

        if user:
            activate_pro_for_user(db, user=user, months=1, payment_id=str(payment_id) if payment_id else None)
            expiry_attr = _pick_expiry_attr(user)
            exp_val = getattr(user, expiry_attr) if (expiry_attr and hasattr(user, expiry_attr)) else None
            return JSONResponse({
                "ok": True,
                "approved": True,   # asumimos aprobado en fallback manual
                "status": status,
                "user_id": user.id,
                "plan": getattr(user, "plan", None),
                "expires_attr": expiry_attr,
                "expires_at": exp_val.isoformat() if isinstance(exp_val, datetime) else None,
                "last_payment_id": getattr(user, "last_payment_id", None),
                "external_reference": raw_ext_ref,
            }, status_code=200)

    # 5) Estados no aprobados o sin usuario
    return JSONResponse({
        "ok": True,
        "approved": False,
        "status": status,
        "user_found": bool(user),
        "user_id": getattr(user, "id", None) if user else None,
        "email_tried": email,
        "external_reference": raw_ext_ref,
    }, status_code=200)
