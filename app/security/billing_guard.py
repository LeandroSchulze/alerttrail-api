# app/deps/billing_guard.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Union

from fastapi import Depends, HTTPException

from app.security import get_current_user_cookie


def _to_aware(dt: Union[datetime, str, None]) -> Optional[datetime]:
    """
    Normaliza una fecha a datetime aware en UTC.
    Acepta datetime naive/aware o strings ISO (con o sin 'Z').
    """
    if isinstance(dt, str):
        try:
            # Soporta ISO con 'Z' o con offset
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return None
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def require_pro(user = Depends(get_current_user_cookie)):
    """
    Dependencia para proteger rutas PRO.
    Lanza 402 (Payment Required) si el usuario no tiene PRO activo.
    """
    # Descubre el atributo de expiración (incluye plan_expires por compatibilidad)
    pro_expiry: Optional[datetime] = None
    for candidate in ("plan_expires", "pro_expires_at", "plan_pro_expires_at", "pro_until", "pro_expiry"):
        if hasattr(user, candidate):
            pro_expiry = _to_aware(getattr(user, candidate))
            break

    now = datetime.now(timezone.utc)
    if not pro_expiry or pro_expiry <= now:
        # Tip para el frontend: mostrar diálogo de upgrade
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Tu plan PRO no está activo.",
                "upgrade_url": "/billing",
                "has_pro_until": pro_expiry.isoformat() if pro_expiry else None,
            },
        )
    return user
