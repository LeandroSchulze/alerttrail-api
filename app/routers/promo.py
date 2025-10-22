from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.security import get_current_user_cookie

router = APIRouter(prefix="/promo", tags=["promo"])

# 🎟️ Cupones disponibles (nombre: {descuento, expiración opcional, descripción})
COUPONS = {
    "ALERT10": {"discount": 10, "expires": None, "desc": "10% de descuento en el plan Pro"},
    "ALERT20": {"discount": 20, "expires": "2025-12-31", "desc": "20% de descuento por tiempo limitado"},
    "PROFREE": {"discount": 100, "expires": None, "desc": "1 mes gratis del plan Pro"},
}

@router.get("/apply")
def apply_coupon(
    code: str = Query(..., description="Código de cupón"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
):
    """Aplica un cupón de descuento o promoción al usuario autenticado."""
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    code = code.strip().upper()

    # Validar existencia
    if code not in COUPONS:
        raise HTTPException(status_code=404, detail="Cupón inválido o inexistente")

    coupon = COUPONS[code]

    # Validar expiración si aplica
    if coupon["expires"]:
        try:
            expiry_date = datetime.strptime(coupon["expires"], "%Y-%m-%d").date()
            if datetime.utcnow().date() > expiry_date:
                raise HTTPException(status_code=400, detail="El cupón ha expirado")
        except ValueError:
            raise HTTPException(status_code=500, detail="Formato de expiración inválido en el cupón")

    # Evitar reutilización o reemplazo
    if getattr(user, "coupon_code", None) == code:
        raise HTTPException(status_code=400, detail="Ya has usado este cupón")
    if getattr(user, "coupon_code", None):
        raise HTTPException(status_code=400, detail=f"Ya tienes aplicado el cupón {user.coupon_code}")

    # Aplicar descuento / beneficio
    user.coupon_code = code
    discount = coupon["discount"]

    # Si es un cupón de 100%, activar plan Pro automáticamente
    if discount == 100:
        user.plan_type = "pro"
        user.is_pro = True

    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "ok": True,
        "code": code,
        "discount": discount,
        "applied_to": user.email,
        "pro_activated": bool(discount == 100),
        "message": f"Cupón '{code}' aplicado correctamente ({coupon['desc']})"
    }
