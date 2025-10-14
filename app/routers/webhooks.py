# app/routers/webhooks.py
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
import os, json, hmac, hashlib

from app.database import get_db
from app.payments.mp_client import sdk
from app.services.subscription import activate_pro

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET")  # opcional
PLAN_PRO_DAYS = int(os.getenv("PLAN_PRO_DAYS", "30"))

@router.post("/mercadopago")
async def mercadopago_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Webhook de Mercado Pago.
    Espera notificaciones con type/topic 'payment' (o 'merchant_order').
    Verifica el pago via API MP y, si está 'approved', activa PRO.
    """
    # 1) Cuerpo de la notificación
    body_bytes = await request.body()
    try:
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        payload = {}

    # 2) (Opcional) Validar firma HMAC de MP si configurás un secreto compartido
    if MP_WEBHOOK_SECRET:
        signature = request.headers.get("x-signature")
        if not signature:
            return {"status": "missing-signature"}
        expected = hmac.new(MP_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return {"status": "invalid-signature"}

    # 3) Extraer tipo e id
    ntype = payload.get("type") or payload.get("topic")  # algunos envían 'topic'
    data = payload.get("data", {}) or {}
    payment_id = data.get("id") or payload.get("resource")

    # 4) Solo procesar pagos
    if ntype in ("payment", "merchant_order") and payment_id:
        # Consultar estado del pago en MP
        try:
            mp_resp = sdk.payment().get(payment_id)  # dict con 'response'
        except Exception:
            return {"status": "mp-api-error"}

        resp = (mp_resp.get("response") or {})
        status = resp.get("status")
        ext_ref = resp.get("external_reference")  # acá guardamos user_id cuando creamos la preferencia

        if status == "approved" and ext_ref:
            try:
                user_id = int(ext_ref)
            except (TypeError, ValueError):
                user_id = None

            if user_id:
                # Activa/renueva PRO por PLAN_PRO_DAYS; idempotente con last_payment_id
                ok = activate_pro(db, user_id=user_id, payment_id=str(payment_id), days=PLAN_PRO_DAYS)
                return {"status": "ok" if ok else "not-found", "user_id": user_id}

    return {"status": "ignored"}
