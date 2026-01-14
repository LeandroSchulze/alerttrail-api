# app/routers/payments_mp.py
from __future__ import annotations

import os
import json
import hmac
import hashlib
import requests

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.orm import Session

# DB / modelos
from app.database import get_db
from app.models import PaymentHistory

# Intentamos importar el webhook oficial. Si no existe, usamos legacy.
try:
    from app.routers.payments import webhook as payments_webhook
    _HAS_MAIN_WEBHOOK = True
except Exception:
    payments_webhook = None  # type: ignore
    _HAS_MAIN_WEBHOOK = False

REQ_TIMEOUT = int(os.getenv("MP_REQ_TIMEOUT_SEC", "25"))


def _mp_headers():
    token = (os.getenv("MP_ACCESS_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("MP_ACCESS_TOKEN no configurado")
    return {"Authorization": f"Bearer {token}"}


def _hmac_valid(secret: str, body: bytes, signature: str | None) -> bool:
    try:
        mac = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()
        return hmac.compare_digest(mac, (signature or "").lower())
    except Exception:
        return False


# =========================
#  LEGACY HANDLER (fallback)
# =========================
async def _legacy_mp_webhook(
    request: Request,
    db: Session,
    x_signature: str | None,
):
    raw = await request.body()

    # Verificación opcional por firma HMAC
    secret = (os.getenv("MP_WEBHOOK_SECRET") or "").strip()
    if secret:
        if not _hmac_valid(secret, raw, x_signature):
            raise HTTPException(status_code=400, detail="Invalid signature")

    payload = json.loads(raw or b"{}")
    data = payload.get("data") or {}

    mp_payment_id = str(data.get("id") or data.get("payment") or "").strip()
    if not mp_payment_id:
        raise HTTPException(status_code=400, detail="Missing payment id")

    # Consultamos el pago en MP
    r = requests.get(
        f"https://api.mercadopago.com/v1/payments/{mp_payment_id}",
        headers=_mp_headers(),
        timeout=REQ_TIMEOUT,
    )
    info = r.json()
    if r.status_code >= 300:
        raise HTTPException(
            status_code=502,
            detail=f"MP lookup error {r.status_code}: {info}",
        )

    status = (info.get("status") or "").lower()
    payer_email = ((info.get("payer") or {}).get("email") or "").lower() or None
    amount_cents = int(round(float(info.get("transaction_amount", 0)) * 100))
    currency = (info.get("currency_id") or "USD").upper()
    external_reference = info.get("external_reference") or ""

    # =========================
    # Parse external_reference
    # =========================
    user_id = None
    org_id = None
    plan = "PRO"
    seats = 1

    for part in external_reference.split("|"):
        if part.startswith("user:"):
            try:
                user_id = int(part.split(":", 1)[1])
            except Exception:
                pass
        elif part.startswith("org:"):
            try:
                org_id = int(part.split(":", 1)[1])
            except Exception:
                pass
        elif part.startswith("plan:"):
            plan = part.split(":", 1)[1].upper()
        elif part.startswith("seats:"):
            try:
                seats = int(part.split(":", 1)[1])
            except Exception:
                pass

    description = (
        f"AlertTrail BIZ ({seats} seats)"
        if plan == "BIZ"
        else "AlertTrail PRO (1 mes)"
    )

    # =========================
    # Idempotencia
    # =========================
    existing = (
        db.query(PaymentHistory)
        .filter(PaymentHistory.payment_id == mp_payment_id)
        .first()
    )
    if existing:
        if existing.status != status:
            existing.status = status
            db.add(existing)
            db.commit()
        return {"ok": True, "dup": True, "status": status}

    # =========================
    # Guardar pago
    # =========================
    ph = PaymentHistory(
        payment_id=mp_payment_id,
        provider="mercado_pago",
        status=status,
        amount_cents=amount_cents,
        currency=currency,
        description=description,
        plan=plan,
        period="monthly",
        external_reference=external_reference,
        payer_email=payer_email,
        origin="webhook",
        user_id=user_id,
    )
    db.add(ph)
    db.commit()

    # =========================
    # Activación de plan
    # =========================
    if status in ("approved", "authorized"):
        # PRO individual
        if plan == "PRO" and user_id:
            try:
                from app.security.billing_guard import activate_user_pro
                activate_user_pro(db, user_id=user_id, months=1)
            except Exception:
                pass

        # BIZ organización
        elif plan == "BIZ" and org_id:
            try:
                from app.security.billing_guard import activate_org_biz
                activate_org_biz(
                    db,
                    org_id=org_id,
                    seats_total=seats,
                    months=1,
                )
            except Exception:
                # Pago queda registrado aunque falte el helper
                pass

    return {"ok": True, "id": mp_payment_id, "status": status}


# =========================
#  ROUTERS (aliases)
# =========================
router = APIRouter(prefix="/payments_mp", tags=["payments-mp"])


@router.post("/webhook", include_in_schema=False)
async def webhook_alias(
    request: Request,
    db: Session = Depends(get_db),
    x_signature: str | None = Header(default=None),
):
    if _HAS_MAIN_WEBHOOK and payments_webhook:
        return await payments_webhook(request)
    return await _legacy_mp_webhook(request, db, x_signature)


alt_router = APIRouter(prefix="/webhooks", tags=["payments-mp"])


@alt_router.post("/mercadopago", include_in_schema=False)
async def webhook_alt(
    request: Request,
    db: Session = Depends(get_db),
    x_signature: str | None = Header(default=None),
):
    if _HAS_MAIN_WEBHOOK and payments_webhook:
        return await payments_webhook(request)
    return await _legacy_mp_webhook(request, db, x_signature)


@alt_router.post("/mp", name="payments_mp_webhook")
async def webhook_mp(
    request: Request,
    db: Session = Depends(get_db),
    x_signature: str | None = Header(default=None),
):
    if _HAS_MAIN_WEBHOOK and payments_webhook:
        return await payments_webhook(request)
    return await _legacy_mp_webhook(request, db, x_signature)
