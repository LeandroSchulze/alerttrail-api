# app/security/billing_guard.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import User


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_user_plan(db: Session, user: User) -> bool:
    """
    Normaliza plan/is_pro según pro_expires_at.
    Devuelve True si cambió algo y se guardó.
    """
    changed = False
    now = _now_utc()

    plan = getattr(user, "plan", None)
    is_pro = getattr(user, "is_pro", None)
    pro_expires_at: Optional[datetime] = getattr(user, "pro_expires_at", None)

    # Compatibilidad: en versiones viejas algunos usuarios quedaban como PRO
    # permanente (is_pro=True / plan="PRO") sin pro_expires_at. No los bajamos
    # a FREE por defecto, porque eso rompe cuentas pagas existentes.
    legacy_permanent_pro = bool(is_pro) and str(plan or "").upper() == "PRO" and not pro_expires_at

    # PRO activo si expira en el futuro, o si es un PRO legacy sin vencimiento
    pro_active = legacy_permanent_pro or bool(pro_expires_at and pro_expires_at > now)

    if pro_active:
        if hasattr(user, "is_pro") and user.is_pro is not True:
            user.is_pro = True
            changed = True
        if hasattr(user, "plan") and (user.plan or "").upper() != "PRO":
            user.plan = "PRO"
            changed = True
    else:
        if hasattr(user, "is_pro") and user.is_pro is not False:
            user.is_pro = False
            changed = True
        if hasattr(user, "plan") and (user.plan or "").upper() != "FREE":
            user.plan = "FREE"
            changed = True

    if changed:
        db.add(user)
        db.commit()
        db.refresh(user)

    return changed
