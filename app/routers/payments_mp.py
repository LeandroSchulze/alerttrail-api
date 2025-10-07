# app/routers/payments_mp.py
from fastapi import APIRouter, Request, HTTPException, Depends, Body
from sqlalchemy.orm import Session
import httpx
import os
from datetime import datetime, timedelta

from app.database import get_db
from app.models import User  # ajustá import según tu estructura

router = APIRouter(prefix="/webhook", tags=["payments-mp"])

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")

async def get_mp_payment(payment_id: str):
    if not MP_ACCESS_TOKEN:
        raise RuntimeError("Falta MP_ACCESS_TOKEN")
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

async def activate_pro_for_user(db: Session, email: str, payment_id: str, months: int = 1):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    # activa PRO por 'months' meses
    now = datetime.utcnow()
    expires = (user.plan_expires if getattr(user, "plan_expires", None) else now)
    if expires < now:
        expires = now
    expires = expires + timedelta(days=30*months)

    user.is_pro = True
    user.plan = "pro"
    user.plan_expires = expires
    # si tenés columnas extra:
    # user.last_payment_id = payment_id
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.post("/mercadopago")
async def mercadopago_webhook(
    body: dict = Body(..., description="Payload enviado por Mercado Pago"),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Recibe notificaciones de MP.
    MP envía algo como: { "action": "payment.created", "data": {"id": "123456789"} }
    Luego consultamos la API de MP para validar el pago.
    """
    # Algunos envíos vienen con query params: topic=payment&id=XXXX (por si preferís request.query_params)
    payment_id = None
    try:
        if "data" in body and "id" in body["data"]:
            payment_id = str(body["data"]["id"])
    except Exception:
        pass
    if not payment_id and request is not None:
        # fallback por query
        q_id = request.query_params.get("id")
        if q_id:
            payment_id = q_id

    if not payment_id:
        raise HTTPException(status_code=400, detail="payment_id no encontrado")

    try:
        payment = await get_mp_payment(payment_id)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Error consultando MP: {e}")

    status = payment.get("status")  # expected 'approved' para pago exitoso
    # Custom: cómo vinculamos el pago al usuario:
    # - Si usaste 'metadata': {"email": "..."} al crear la preferencia/checkout, MP lo devuelve en payment["metadata"]
    # - Alternativa: payment["payer"]["email"] (no siempre es igual al email de cuenta en tu app)
    metadata = payment.get("metadata") or {}
    email = metadata.get("email") or (payment.get("payer") or {}).get("email")

    if not email:
        # Si no tenemos email en metadata, podrías mapear por external_reference
        email = payment.get("external_reference")  # si guardaste el email ahí

    if not email:
        # última chance: rechazamos y registramos
        raise HTTPException(status_code=400, detail="No se pudo inferir email del usuario desde MP (metadata/external_reference)")

    if status == "approved":
        user = await activate_pro_for_user(db, email=email, payment_id=payment_id, months=1)
        return {"ok": True, "email": user.email, "is_pro": user.is_pro, "plan_expires": user.plan_expires.isoformat()}
    else:
        # Podés manejar 'pending', 'in_process', 'rejected' etc.
        return {"ok": False, "status": status, "detail": "Pago no aprobado aún"}
