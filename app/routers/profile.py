from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.security import (
    get_current_user_cookie,  # Consistente con el resto de los routers
    get_password_hash,
    verify_password,
)

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/me")
def get_profile(user: User = Depends(get_current_user_cookie)):
    """Devuelve la información básica del perfil del usuario autenticado."""
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    return {
        "id": user.id,
        "email": user.email,
        "name": getattr(user, "name", None),
        "plan": getattr(user, "plan", "FREE"),
        "is_pro": getattr(user, "is_pro", False),
        "pro_expires_at": getattr(user, "pro_expires_at", None),
        "coupon_code": getattr(user, "coupon_code", None),
    }


@router.post("/change-password")
def change_password(
    old_password: str = Body(..., embed=True, description="Contraseña actual"),
    new_password: str = Body(..., embed=True, description="Nueva contraseña"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
):
    """
    Permite al usuario cambiar su contraseña.
    Valida la actual, genera hash nuevo y guarda en la base.
    """
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    if not verify_password(old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Contraseña actual incorrecta")

    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="La nueva contraseña debe tener al menos 6 caracteres")

    user.hashed_password = get_password_hash(new_password)
    db.add(user)
    db.commit()

    return {"ok": True, "detail": "Contraseña actualizada correctamente"}
