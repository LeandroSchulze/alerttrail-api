# app/security/billing_guard.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user_cookie


def _now_utc_naive() -> datetime:
    """UTC naive (sin tzinfo) para comparar con campos DateTime naive de la DB."""
    return datetime.utcnow()


def _now_utc_aware() -> datetime:
    """UTC aware para respuestas/errores."""
    return datetime.now(timezone.utc)


def _to_aware(dt: Union[datetime, str, None]) -> Optional[datetime]:
    """Normaliza una fecha a datetime aware en UTC.

    Acepta:
      - datetime naive  -> la considera UTC
      - datetime aware -> la normaliza a UTC
      - str ISO 8601   -> intenta parsear
      - None           -> None
    """
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            # Lo tratamos como UTC naive
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(dt, str):
        try:
            parsed = datetime.fromisoformat(dt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None
    return None


def normalize_user_plan(db: Session, user: User) -> User:
    """Normaliza campos de PRO / trial de un usuario.

    Objetivos:
      - Unificar el uso de:
          user.plan
          user.pro_expires_at
          user.pro_source ("subscription" | "trial" | None)
          user.trial_started_at
          user.trial_expires_at
          user.had_trial (bool)
      - Si el trial terminó y no hay PRO pago activo -> baja a FREE.
      - Mantener compatibilidad con campos legacy (plan_expires).

    Es segura de llamar muchas veces; solo hace commit si hay cambios.
    """
    changed = False
    now_naive = _now_utc_naive()

    # --------- Campos base ----------
    plan_raw = (getattr(user, "plan", None) or "FREE").upper()
    pro_expires_at: Optional[datetime] = getattr(user, "pro_expires_at", None)
    pro_source: Optional[str] = getattr(user, "pro_source", None)
    trial_started_at: Optional[datetime] = getattr(user, "trial_started_at", None)
    trial_expires_at: Optional[datetime] = getattr(user, "trial_expires_at", None)
    had_trial: bool = bool(getattr(user, "had_trial", False))

    # Campos legacy
    legacy_plan_expires: Optional[datetime] = getattr(user, "plan_expires", None)

    # --------- Migra datos legacy (plan_expires) ----------
    if not pro_expires_at and legacy_plan_expires and plan_raw in {"PRO", "BIZ", "EMPRESA", "EMPRESAS"}:
        pro_expires_at = legacy_plan_expires
        user.pro_expires_at = legacy_plan_expires
        if not pro_source:
            user.pro_source = "subscription"
            pro_source = "subscription"
        changed = True

    # --------- Trial expirado ----------
    if trial_expires_at and trial_expires_at <= now_naive and not had_trial:
        user.had_trial = True
        had_trial = True
        changed = True

    # --------- Determinar si tiene PRO pago activo ----------
    has_paid_pro = False
    if pro_expires_at and pro_expires_at > now_naive and (pro_source or "").lower() == "subscription":
        has_paid_pro = True

    # --------- Determinar si está en trial PRO activo ----------
    has_trial_pro = False
    if trial_expires_at and trial_expires_at > now_naive and (pro_source or "").lower() == "trial":
        has_trial_pro = True

    # --------- Ajustar plan según estado ----------
    if has_paid_pro:
        if plan_raw in {"FREE", "", "BASIC"}:
            user.plan = "PRO"
            changed = True
    else:
        if has_trial_pro:
            if plan_raw in {"FREE", "", "BASIC"}:
                user.plan = "PRO"
                changed = True
        else:
            # No PRO pago ni trial activo
            if plan_raw in {"PRO", "BIZ", "EMPRESA", "EMPRESAS"}:
                user.plan = "FREE"
                if hasattr(user, "is_pro"):
                    user.is_pro = False
                changed = True

            if trial_expires_at and trial_expires_at <= now_naive and not had_trial:
                user.had_trial = True
                had_trial = True
                changed = True

    # --------- Sincronizar flag is_pro ----------
    flag_is_pro = has_paid_pro or has_trial_pro
    if hasattr(user, "is_pro"):
        if bool(user.is_pro) != flag_is_pro:
            user.is_pro = flag_is_pro
            changed = True

    # --------- Limpieza opcional de plan_expires ----------
    if legacy_plan_expires and legacy_plan_expires <= now_naive and not has_paid_pro:
        try:
            from sqlalchemy import inspect as _sa_inspect
            insp = _sa_inspect(user)
            if "plan_expires" in insp.attrs:
                user.plan_expires = None
                changed = True
        except Exception:
            pass

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

    Normalmente se llama desde el webhook de Mercado Pago.
    """
    try:
        from app.services.subscription import activate_pro, PLAN_PRO_DAYS_DEFAULT
    except Exception:
        activate_pro = None
        PLAN_PRO_DAYS_DEFAULT = 30  # fallback

    user: Optional[User] = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None

    now = _now_utc_naive()

    if activate_pro and source == "subscription":
        days = months * int(PLAN_PRO_DAYS_DEFAULT or 30)
        ok = activate_pro(db, user_id=user_id, payment_id=None, days=days)
        if not ok:
            return None
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None
    else:
        current_expiry = getattr(user, "pro_expires_at", None)
        if current_expiry and current_expiry > now:
            base = current_expiry
        else:
            base = now
        new_expiry = base + timedelta(days=30 * max(1, months))

        user.pro_expires_at = new_expiry
        user.pro_source = source or "subscription"
        user.plan = "PRO"
        if hasattr(user, "is_pro"):
            user.is_pro = True
        if not getattr(user, "had_trial", False):
            user.had_trial = True

        db.add(user)
        db.commit()
        db.refresh(user)

    user = normalize_user_plan(db, user)
    return user


def require_pro_user(
    db: Session = Depends(get_db),
    current=Depends(get_current_user_cookie),
) -> User:
    """Dependencia para rutas PRO (alerts, reglas, auditoría, etc)."""
    user: Optional[User] = db.query(User).filter(User.id == current["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")

    user = normalize_user_plan(db, user)

    pro_expiry_aware = _to_aware(getattr(user, "pro_expires_at", None))
    now = _now_utc_aware()

    if not pro_expiry_aware or pro_expiry_aware <= now:
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Tu plan PRO no está activo.",
                "upgrade_url": "/billing/subscriptions",
                "has_pro_until": pro_expiry_aware.isoformat() if pro_expiry_aware else None,
            },
        )

    return user
