# app/security/billing_guard.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user_cookie


def _to_aware(dt: Union[datetime, str, None]) -> Optional[datetime]:
    """Normaliza una fecha a datetime aware en UTC.
    Acepta datetime naive/aware o strings ISO (con o sin 'Z')."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(dt, str):
        value = dt.strip()
        if not value:
            return None
        try:
            # Soportar timestamps estilo 2025-01-01T00:00:00Z
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            dt_parsed = datetime.fromisoformat(value)
            if dt_parsed.tzinfo is None:
                dt_parsed = dt_parsed.replace(tzinfo=timezone.utc)
            else:
                dt_parsed = dt_parsed.astimezone(timezone.utc)
            return dt_parsed
        except Exception:
            return None
    return None


def _now_utc_aware() -> datetime:
    return datetime.now(timezone.utc)


def _now_naive_utc() -> datetime:
    # El modelo User usa datetime.utcnow() en varios helpers,
    # así que mantenemos el mismo estilo (naive en UTC).
    return datetime.utcnow()


def normalize_user_plan(db: Session, user: User) -> User:
    """Normaliza campos de trial / PRO para un usuario.

    - Migra campos legacy (trial_days / plan_expires) hacia trial_expires_at.
    - Marca had_trial cuando el trial ya terminó.
    - Deja pro_expires_at listo para ser usado por activate_user_pro.
    - Es segura de llamar muchas veces y no lanza excepciones fatales.
    """
    changed = False
    now = _now_naive_utc()

    # --- Trial ---
    trial_started = getattr(user, "trial_started_at", None)
    trial_expires = getattr(user, "trial_expires_at", None)

    # Campos "legacy" que pueden existir en algunas DB / versiones
    legacy_trial_days = getattr(user, "trial_days", None)
    legacy_plan_expires = getattr(user, "plan_expires", None)

    # Si no tenemos trial_expires_at pero sí datos legacy, los usamos
    if not trial_expires:
        if trial_started and isinstance(legacy_trial_days, int):
            trial_expires = trial_started + timedelta(days=legacy_trial_days)
            user.trial_expires_at = trial_expires
            changed = True
        elif isinstance(legacy_plan_expires, datetime):
            # En versiones viejas se usaba plan_expires para el trial
            user.trial_expires_at = legacy_plan_expires
            trial_expires = legacy_plan_expires
            changed = True

    # Si el trial ya terminó y no está marcado
    if trial_expires and trial_expires <= now and not getattr(user, "had_trial", False):
        user.had_trial = True
        changed = True

    # --- PRO desde suscripción ---
    pro_expires = user.pro_expires_at
    if pro_expires and isinstance(pro_expires, datetime) and pro_expires.tzinfo is not None:
        # Guardamos naive en UTC para ser consistentes con el resto del modelo
        user.pro_expires_at = pro_expires.astimezone(timezone.utc).replace(tzinfo=None)
        changed = True

    if changed:
        try:
            db.add(user)
            db.commit()
            db.refresh(user)
        except Exception:
            db.rollback()
    return user


def activate_user_pro(
    db: Session,
    user_id: int,
    months: int = 1,
    *,
    source: str = "subscription",
) -> Optional[User]:
    """Activa o extiende el plan PRO de un usuario.

    - Si ya tenía PRO con pro_expires_at en el futuro, suma `months` desde esa fecha.
    - Si estaba vencido o sin PRO, arranca `months` desde ahora.
    - Marca `pro_source` y `had_trial` si corresponde.
    """
    user: Optional[User] = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None

    now = _now_naive_utc()
    base = user.pro_expires_at or now
    if base < now:
        base = now

    # Meses aproximados en días (30): suficiente para uso general.
    extra_days = 30 * max(1, int(months))
    new_expiry = base + timedelta(days=extra_days)

    # Normalizamos el plan: si no es PRO/BIZ, lo pasamos a PRO
    current_plan = (user.plan or "FREE").upper()
    if current_plan not in ("PRO", "BIZ"):
        current_plan = "PRO"
    user.plan = current_plan

    user.pro_expires_at = new_expiry
    if source:
        user.pro_source = source

    # Si estaba en trial y ya venció, lo damos por finalizado
    if user.trial_expires_at and user.trial_expires_at <= now:
        user.had_trial = True

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def require_pro_user(
    payload = Depends(get_current_user_cookie),
    db: Session = Depends(get_db),
) -> User:
    """Dependencia para endpoints que requieren un usuario con PRO activo.

    Devuelve el objeto User si tiene acceso PRO (trial o suscripción vigente).
    En caso contrario lanza HTTP 402 (Payment Required) con datos para UI.
    """
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")

    user: Optional[User] = db.query(User).filter(User.id == user_id).first()
    if not user or not getattr(user, "is_active", True):
        raise HTTPException(status_code=401, detail="Usuario no válido")

    # Normalizamos datos de plan/trial
    normalize_user_plan(db, user)

    # Determinar hasta cuándo tiene PRO (trial o suscripción)
    pro_expiry: Optional[datetime] = None
    if user.pro_expires_at:
        pro_expiry = user.pro_expires_at
    elif user.trial_expires_at:
        pro_expiry = user.trial_expires_at

    pro_expiry_aware = _to_aware(pro_expiry)
    now = _now_utc_aware()

    if not pro_expiry_aware or pro_expiry_aware <= now:
        # Tip para el frontend: mostrar diálogo de upgrade
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Tu plan PRO no está activo.",
                "upgrade_url": "/billing",
                "has_pro_until": pro_expiry_aware.isoformat() if pro_expiry_aware else None,
            },
        )

    return user
