import os
import datetime as dt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import get_current_user_id
from app.models import User, AllowedIP
from app.utils.ip import get_client_ip


# ---- Helpers ----
def _is_paid(user: User) -> bool:
    """Usuario con plan PRO o BUSINESS vigente."""
    now = dt.datetime.utcnow()
    return user.plan in ("PRO", "BUSINESS") and (
        user.plan_expires is None or user.plan_expires > now
    )


def _ip_enforcement_on() -> bool:
    return os.getenv("IP_ENFORCEMENT", "false").lower() == "true"


# ---- Guards públicos ----
def require_pro(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> int:
    """Exige plan PRO/BUSINESS activo (402 si no)."""
    user = db.query(User).get(user_id)
    if not user or not _is_paid(user):
        raise HTTPException(status_code=402, detail="Se requiere plan PRO o Business")
    return user_id


def require_admin(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> int:
    """Exige rol admin (403 si no)."""
    user = db.query(User).get(user_id)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    return user_id


def require_ip_allowed(
    request: Request,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> int:
    """Si IP_ENFORCEMENT=true, sólo permite IPs registradas. Autobindea la primera."""
    if not _ip_enforcement_on():
        return user_id

    ip = get_client_ip(request)

    # ¿ya está permitida esta IP?
    allowed = (
        db.query(AllowedIP)
        .filter(AllowedIP.user_id == user_id, AllowedIP.ip == ip)
        .first()
    )
    if allowed:
        return user_id

    # si el usuario no tiene ninguna IP, guardamos la actual
    count = db.query(AllowedIP).filter(AllowedIP.user_id == user_id).count()
    max_ips = int(os.getenv("IP_MAX_PER_USER", "1"))
    if count == 0:
        db.add(AllowedIP(user_id=user_id, ip=ip, label="auto"))
        db.commit()
        return user_id

    # límite alcanzado o IP distinta
    raise HTTPException(status_code=403, detail="IP no autorizada")
