from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.security import get_current_user_cookie

router = APIRouter(prefix="/promo", tags=["promo"])

COUPONS = {
    "ALERT10": 10,
    "ALERT20": 20,
    "PROFREE": 100,
}

@router.get("/apply")
def apply_coupon(
    code: str = Query(..., description="Código de cupón"),
    db = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    code = code.strip().upper()
    if code not in COUPONS:
        raise HTTPException(status_code=404, detail="Cupón inválido")
    discount = COUPONS[code]
    user.coupon_code = code
    db.add(user)
    db.commit()
    return {"ok": True, "discount": discount}
