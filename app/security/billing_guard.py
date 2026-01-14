# app/security/billing_guard.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import User, Organization


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# USER / PRO
# ============================================================
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

    # PRO legacy sin vencimiento → no se baja
    legacy_permanent_pro = bool(is_pro) and str(plan or "").upper() == "PRO" and not pro_expires_at

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


def activate_user_pro(db: Session, user_id: int, months: int = 1) -> None:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return

    now = _now_utc()
    base = user.pro_expires_at if user.pro_expires_at and user.pro_expires_at > now else now
    user.pro_expires_at = base.replace(month=base.month + months)

    user.is_pro = True
    user.plan = "PRO"

    db.add(user)
    db.commit()
    db.refresh(user)


# ============================================================
# ORG / BIZ
# ============================================================
def activate_org_biz(
    db: Session,
    org_id: int,
    seats_total: int,
    months: int = 1,
) -> None:
    """
    Activa o renueva BIZ para una organización.
    NO toca usuarios individuales.
    """
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        return

    now = _now_utc()

    # Plan
    org.plan = "BIZ"

    # Seats
    if not org.seats_total or org.seats_total < seats_total:
        org.seats_total = seats_total

    # Expiración (si existe campo)
    if hasattr(org, "biz_expires_at"):
        base = (
            org.biz_expires_at
            if org.biz_expires_at and org.biz_expires_at > now
            else now
        )
        org.biz_expires_at = base.replace(month=base.month + months)

    db.add(org)
    db.commit()
    db.refresh(org)
