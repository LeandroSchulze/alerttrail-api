# app/services/pro_plan.py
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import User

def activate_pro(db: Session, user_id: int, months: int = 1):
    """
    Activa/renueva PRO de un usuario. Si el modelo no tiene pro_until,
    setea solo plan='PRO'. Si tiene pro_until, extiende meses.
    """
    u = db.query(User).get(user_id)
    if not u:
        return False

    # set básico
    if hasattr(u, "plan"):
        u.plan = "PRO"

    # si existe columna pro_until, extendemos
    if hasattr(u, "pro_until"):
        now = datetime.utcnow()
        base = u.pro_until if (getattr(u, "pro_until") and u.pro_until > now) else now
        u.pro_until = base + timedelta(days=30 * months)

    db.commit()
    return True
