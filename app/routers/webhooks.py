from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
import os, json, hmac, hashlib

from app.database import get_db
from app.payments.mp_client import sdk
from app.services.subscription import activate_pro

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET")
PLAN_PRO_DAYS = int(os.getenv("PLAN_PRO_DAYS", "30"))

@router.post("/mercadopago")
async def mercadopago_webhook(request: Request, db: Session = Depends(get_db)):
    body_bytes = await request.body()
    try:
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        payload = {}

    # Firma opcional (si configuraste un secreto)
    if MP_WEBHOOK_SECRET:
        signature = request.headers.get("x-signature")
        if not signature:
            return {"status": "missing-signature"}
        expected = hmac.new(MP_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return {"status": "invalid-signature"}

    ntype = payload.get("type") or payload.get("topic")
    data = payload.get("data", {})
    payment_id = data.get("id") or payload.get("resource")

    if ntype in ("payment", "merchant_order") and payment_id:
        payment = sdk.payment().get(payment_id)
        resp = (payment.get("response") or {})
        status = resp.get("status")
        ext_ref = resp.get("external_reference")

        if status == "approved" and ext_ref:
            try:
                user_id = int(ext_ref)
            except ValueError:
                user_id = None
            if user_id:
                activate_pro(db, user_id=user_id, payment_id=str(payment_id), days=PLAN_PRO_DAYS)
                return {"status": "ok", "user_id": user_id}

    return {"status": "ignored"}
