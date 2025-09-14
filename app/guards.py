import os
import datetime as dt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import get_current_user_id
from app.models import User, AllowedIP
from app.utils.ip import get_client_ip

# ----- helpers -----
def _is_paid(user: User) -> bool:
    now = dt.datetime.utcnow()
    return user.plan in ("PRO", "BUSINESS") and (
        user.plan_expires is None or user.plan_expires > now
    )

def _ip_on() -> bool:
    return os.getenv("IP_ENFORCEMENT", "false").lower() == "true"

# ----- guards públicos -----
def require_pro(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> int:
    user = db.query(User).get(user_id)
    if not user or not _is_paid(user):
        raise HTTPException(status_code=402, detail="Se requiere plan PRO o Business")
    return user_id

def require_admin(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> int:
    user = db.query(User).get(user_id)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    return user_id

def require_ip_allowed(
    request: Request,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> int:
    if not _ip_on():
        return user_id
    ip = get_client_ip(request)
    allowed = (
        db.query(AllowedIP)
        .filter(AllowedIP.user_id == user_id, AllowedIP.ip == ip)
        .first()
    )
    if allowed:
        return user_id
    count = db.query(AllowedIP).filter(AllowedIP.user_id == user_id).count()
    if count == 0:
        db.add(AllowedIP(user_id=user_id, ip=ip, label="auto"))
        db.commit()
        return user_id
    raise HTTPException(status_code=403, detail="IP no autorizada")
