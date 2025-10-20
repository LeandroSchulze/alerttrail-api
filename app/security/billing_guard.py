# app/security/billing_guard.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Iterable

from sqlalchemy.orm import Session

from app.models import User

# --- helpers internos -------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _get_expiry_attr(u: User) -> Optional[str]:
    # Compatibilidad con distintos nombres históricos
    for attr in ("pro_expires_at", "plan_expires", "pro_until"):
        if hasattr(u, attr):
            return attr
    return None

def _is_active_pro(u: User, now: Optional[datetime] = None) -> bool:
    now = now or _now_utc()
    exp_attr = _get_expiry_attr(u)
    if not exp_attr:
        return False
    exp_val = getattr(u, exp_attr, None)
    if not isinstance(exp_val, datetime):
        return False
    return exp_val > now

# --- API pública ------------------------------------------------------------

def normalize_user_plan(db: Session, u: User, *, now: Optional[datetime] = None) -> bool:
    """
    Asegura coherencia del plan del usuario según expiración.
    - Si venció PRO -> baja a FREE y limpia flags.
    - Si sigue vigente -> garantiza plan "PRO" y opcionalmente is_pro=True si existe.

    Devuelve True si hubo cambios y se persistieron.
    """
    if not isinstance(u, User):
        return False

    now = now or _now_utc()
    changed = False

    # “BIZ/EMPRESAS” no se baja automáticamente acá.
    plan = (getattr(u, "plan", "") or "").upper()
    is_biz = plan in {"BIZ", "EMPRESAS", "EMPRESA"}

    if is_biz:
        # Asegurar consistencia mínima
        if hasattr(u, "is_pro") and not getattr(u, "is_pro", False):
            u.is_pro = True
            changed = True
        # No tocamos expiraciones para BIZ en este guard.
    else:
        if _is_active_pro(u, now):
            # Garantizar plan PRO si está vigente
            if plan != "PRO":
                u.plan = "PRO"; changed = True
            if hasattr(u, "is_pro") and not getattr(u, "is_pro", False):
                u.is_pro = True; changed = True
            if hasattr(u, "pro_source") and not getattr(u, "pro_source", None):
                # Marcar fuente por defecto si venía vacía
                u.pro_source = getattr(u, "pro_source", None) or "subscription"; changed = True
        else:
            # Vencido -> bajar a FREE y limpiar flags
            if plan != "FREE":
                u.plan = "FREE"; changed = True
            if hasattr(u, "is_pro") and getattr(u, "is_pro", False):
                u.is_pro = False; changed = True
            if hasattr(u, "pro_source") and getattr(u, "pro_source", None):
                u.pro_source = None; changed = True

    if changed:
        db.add(u)
        db.commit()
        db.refresh(u)
    return changed


def bulk_normalize_user_plans(db: Session, *, chunk_size: int = 500) -> int:
    """
    Recorre usuarios y normaliza planes. Pensado para correr en un job diario.
    Devuelve la cantidad de usuarios modificados.
    """
    now = _now_utc()
    total_changed = 0

    # En dos pasadas simples para bases sin funciones avanzadas:
    # 1) Usuarios con plan PRO vencido -> bajar
    q1 = db.query(User).filter((User.plan == "PRO"))
    for u in q1.yield_per(chunk_size):
        if normalize_user_plan(db, u, now=now):
            total_changed += 1

    # 2) Opcional: asegurar consistencia BIZ
    q2 = db.query(User).filter(User.plan.in_(["BIZ", "EMPRESAS", "EMPRESA"]))
    for u in q2.yield_per(chunk_size):
        if normalize_user_plan(db, u, now=now):
            total_changed += 1

    return total_changed


def guard_user_by_id(db: Session, user_id: int) -> bool:
    """
    Carga un usuario por id y aplica normalize_user_plan. Devuelve True si cambió.
    """
    if not user_id:
        return False
    u = db.query(User).get(int(user_id))
    if not u:
        return False
    return normalize_user_plan(db, u)
