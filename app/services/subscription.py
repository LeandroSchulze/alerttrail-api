# app/services/subscription.py
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import User

PLAN_PRO_DAYS_DEFAULT = 30

def activate_pro(
    db: Session,
    user_id: int,
    payment_id: str | None = None,
    days: int | None = None
) -> bool:
    """
    Activa/renueva el plan PRO del usuario. Idempotente con last_payment_id.
    - Si PRO sigue activo: extiende pro_expires_at.
    - Si PRO vencido o FREE: inicia nuevo período.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False

    now = datetime.utcnow()
    period = days or PLAN_PRO_DAYS_DEFAULT

    # Idempotencia simple por payment_id (si viene del webhook de MP)
    if payment_id and user.last_payment_id == str(payment_id):
        return True

    # Extensión / activación
    if user.pro_expires_at and user.pro_expires_at > now:
        user.pro_expires_at = user.pro_expires_at + timedelta(days=period)
    else:
        user.pro_expires_at = now + timedelta(days=period)

    user.plan = "PRO"
    user.pro_source = "subscription"
    if payment_id:
        user.last_payment_id = str(payment_id)
    user.updated_at = now

    # Si nunca tuvo trial, lo marcamos para evitar re-trials futuros (opcional)
    if not user.had_trial:
        user.had_trial = True

    db.add(user)
    db.commit()
    db.refresh(user)
    return True
