import os, datetime as dt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import get_current_user_id
from app.models import User, AllowedIP
from app.utils.ip import get_client_ip

def _is_paid(user: User) -> bool:
    now = dt.datetime.utcnow()
    return user.plan in ('PRO', 'BUSINESS') and (user.plan_expires is None or user.plan_expires > now)

def require_pro(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> int:
    user = db.query(User).get(user_id)
    if not user or not _is_paid(user):
        # 402 Payment Required → en main lo redirigimos a /billing para HTML
        raise HTTPException(status_code=402, detail="Se requiere plan PRO o Business")
    return user_id

# --- (opcional) Enforcement de IP ---
def _ip_enforcement_on() -> bool:
    return os.getenv("IP_ENFORCEMENT", "false").lower() == "true"

def require_ip_allowed(request: Request, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> int:
    if not _ip_enforcement_on():
        return user_id
    ip = get_client_ip(request)
    if db.query(AllowedIP).filter(AllowedIP.user_id == user_id, AllowedIP.ip == ip).first():
        return user_id
    # Autobind primera IP
    cnt = db.query(AllowedIP).filter(AllowedIP.user_id == user_id).count()
    max_ips = int(os.getenv("IP_MAX_PER_USER", "1"))
    if cnt == 0:
        db.add(AllowedIP(user_id=user_id, ip=ip, label="auto"))
        db.commit()
        return user_id
    raise HTTPException(status_code=403, detail="IP no autorizada")
