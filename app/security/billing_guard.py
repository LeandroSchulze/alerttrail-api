# app/deps/billing_guard.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException

from app.security import get_current_user_cookie

def require_pro(user = Depends(get_current_user_cookie)):
    """
    Dependencia para proteger rutas PRO.
    Lanza 402 (Payment Required) si el usuario no tiene PRO activo.
    """
    # Descubre el atributo de expiración
    pro_expiry: Optional[datetime] = None
    for candidate in ("pro_expires_at", "plan_pro_expires_at", "pro_until", "pro_expiry"):
        if hasattr(user, candidate):
            pro_expiry = getattr(user, candidate)
            break

    now = datetime.now(timezone.utc)
    if not pro_expiry or pro_expiry <= now:
        # Tip para el frontend: mostrar diálogo de upgrade
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Tu plan PRO no está activo.",
                "upgrade_url": "/payments/upgrade",  # si tienes una vista
                "has_pro_until": pro_expiry.isoformat() if pro_expiry else None,
            },
        )
    return user
