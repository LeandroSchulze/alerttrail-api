# app/routers/payments_mp.py
from __future__ import annotations
import os, json, hmac, hashlib, requests
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

# DB / modelos
from app.database import get_db
from app.models import PaymentHistory

# Intentamos importar el webhook oficial. Si no existe, usamos el legacy de abajo.
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
async def _legacy_mp_webhook(request: Request, db: Session, x_signature: str | None):
    raw = await request.body()

    # Verificación opcional por firma HMAC (si configurás MP_WEBHOOK_SECRET)
    secret = (os.getenv("MP_WEBHOOK_SECRET") or "").strip()
    if secret:
        if not _hmac_valid(secret, raw, x_signature):
            raise HTTPException(status_code=400, detail="Invalid signature")

    payload = json.loads(raw or b"{}")
    data = payload.get("data") or {}

    # MP puede enviar {data:{id}} o {data:{payment}}
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

    # Idempotencia
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
            activate_user_pro(db, user_id=user_id, months=1)
        except Exception:
            # Si no existe el helper, lo resolverá normalize_user_plan luego
            pass

    return {"ok": True, "id": mp_payment_id, "status": status}

# =========================
#  ROUTERS (aliases + legacy)
# =========================

# Alias moderno
router = APIRouter(prefix="/payments_mp", tags=["payments-mp"])

@router.post("/webhook", include_in_schema=False)
async def webhook_alias(request: Request, db: Session = Depends(get_db), x_signature: str | None = Header(default=None)):
    """
    Alias hacia el webhook oficial (/payments/webhook).
    Si no existe, usa el handler legacy (compatibilidad completa).
    """
    if _HAS_MAIN_WEBHOOK and payments_webhook:
        return await payments_webhook(request)
    return await _legacy_mp_webhook(request, db, x_signature)

# Alias clásico
alt_router = APIRouter(prefix="/webhooks", tags=["payments-mp"])

@alt_router.post("/mercadopago", include_in_schema=False)
async def webhook_alt(request: Request, db: Session = Depends(get_db), x_signature: str | None = Header(default=None)):
    if _HAS_MAIN_WEBHOOK and payments_webhook:
        return await payments_webhook(request)
    return await _legacy_mp_webhook(request, db, x_signature)

# Mantener compatibilidad con el endpoint que ya usaban /webhooks/mp
@alt_router.post("/mp", name="payments_mp_webhook")
async def webhook_mp(request: Request, db: Session = Depends(get_db), x_signature: str | None = Header(default=None)):
    if _HAS_MAIN_WEBHOOK and payments_webhook:
        return await payments_webhook(request)
    return await _legacy_mp_webhook(request, db, x_signature)
