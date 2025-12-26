# app/security/billing_guard.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user_cookie


def _utcnow_naive() -> datetime:
    # Comparaciones seguras contra DB (SQLite suele guardar naive)
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_user_plan(db: Session, user: User) -> User:
    """
    Normaliza el estado PRO/TRIAL/FREE en base al modelo REAL del proyecto.

    Campos que existen en tu User:
    - plan (str)
    - is_pro (bool)
    - pro_expires_at (datetime|None)
    - trial_expires_at (datetime|None)
    - trial_used (bool)

    Evita campos inexistentes como pro_source/had_trial.
    """
    now = _utcnow_naive()

    plan = (getattr(user, "plan", None) or "FREE").upper()
    is_admin = (getattr(user, "role", "") or "").lower() == "admin"

    pro_expires_at = getattr(user, "pro_expires_at", None)
    trial_expires_at = getattr(user, "trial_expires_at", None)

    # PRO activo si expira en el futuro
    pro_active = bool(pro_expires_at and pro_expires_at > now)

    # Si es admin, siempre PRO
    if is_admin:
        plan = "PRO"
        try:
            user.plan = "PRO"
            user.is_pro = True
        except Exception:
            pass
        return user

    # Si pro_active => PRO
    if pro_active:
        try:
            user.plan = "PRO"
            user.is_pro = True
        except Exception:
            pass
        return user

    # TRIAL activo si expira en el futuro
    trial_active = bool(trial_expires_at and trial_expires_at > now)
    if trial_active:
        try:
            user.plan = "TRIAL"
            # en trial no es "pro"
            user.is_pro = False
        except Exception:
            pass
        return user

    # Si llegó acá: no hay pro ni trial activos -> FREE
    try:
        user.plan = "FREE"
        user.is_pro = False
    except Exception:
        pass
    return user


def get_current_user_db(request: Request, db: Optional[Session] = None) -> User:
    """
    Devuelve el usuario autenticado + plan normalizado.
    """
    payload = get_current_user_cookie(request)
    uid = int(payload["sub"])

    if db is None:
        with next(get_db()) as db2:
            user = db2.query(User).filter(User.id == uid).first()
            if not user:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
            normalize_user_plan(db2, user)
            return user

    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    normalize_user_plan(db, user)
    return user


def require_pro(user: User) -> None:
    plan = (getattr(user, "plan", None) or "FREE").upper()
    role = (getattr(user, "role", None) or "").lower()

    if role == "admin":
        return
    if plan == "PRO":
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requiere plan PRO")
