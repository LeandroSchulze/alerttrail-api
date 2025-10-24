# app/routers/payments_mp.py
from __future__ import annotations
import os, json, hmac, hashlib, requests
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PaymentHistory

router = APIRouter(prefix="/webhooks", tags=["payments-mp"])

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

@router.post("/mp", name="payments_mp_webhook")
async def mp_webhook(request: Request, db: Session = Depends(get_db), x_signature: str | None = Header(default=None)):
    raw = await request.body()

    # Verificación opcional por firma HMAC (si configurás MP_WEBHOOK_SECRET)
    secret = (os.getenv("MP_WEBHOOK_SECRET") or "").strip()
    if secret:
        if not _hmac_valid(secret, raw, x_signature):
            raise HTTPException(status_code=400, detail="Invalid signature")

    payload = json.loads(raw or b"{}")
    data = payload.get("data") or {}
    mp_payment_id = str(data.get("id") or data.get("payment") or "").strip()
    if not mp_payment_id:
        raise HTTPException(status_code=400, detail="Missing payment id")

    # Consultamos el pago en MP como fuente de verdad
    r = requests.get(
        f"https://api.mercadopago.com/v1/payments/{mp_payment_id}",
        headers=_mp_headers(),
        timeout=REQ_TIMEOUT,
    )
    info = r.json()
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"MP lookup error {r.status_code}: {info}")

    status = (info.get("status") or "").lower()
    payer_email = ((info.get("payer") or {}).get("email") or "").lower() or None
    amount_cents = int(round(float(info.get("transaction_amount", 0)) * 100))
    currency = (info.get("currency_id") or "USD").upper()
    external_reference = info.get("external_reference") or ""

    # Idempotencia: si ya existe, no duplicar. Actualiza si cambió el estado.
    existing = db.query(PaymentHistory).filter(PaymentHistory.payment_id == mp_payment_id).first()
    if existing:
        if existing.status != status:
            existing.status = status
            db.add(existing); db.commit()
        return {"ok": True, "dup": True, "status": status}

    # Resolver user_id desde external_reference "user:<id>|..."
    user_id = None
    for part in external_reference.split("|"):
        if part.startswith("user:"):
            try:
                user_id = int(part.split(":", 1)[1])
            except Exception:
                pass

    ph = PaymentHistory(
        payment_id=mp_payment_id,
        provider="mercado_pago",
        status=status,
        amount_cents=amount_cents,
        currency=currency,
        description="AlertTrail PRO (1 mes)",
        plan="PRO",
        period="monthly",
        external_reference=external_reference,
        payer_email=payer_email,
        origin="webhook",
        user_id=user_id,
    )
    db.add(ph); db.commit()

    # Activación/renovación PRO cuando corresponde
    if status in ("approved", "authorized") and user_id:
        try:
            from app.security.billing_guard import activate_user_pro
            # Suma 1 mes desde hoy (o desde la fecha de expiración actual si es futura — depende de tu helper)
            activate_user_pro(db, user_id=user_id, months=1)
        except Exception:
            # Si no existe el helper, lo puede manejar normalize_user_plan luego
            pass

    return {"ok": True, "id": mp_payment_id, "status": status}
