from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import get_current_user_cookie
from app.models import User

router = APIRouter(prefix="/subscription", tags=["subscription"])

@router.get("/me")
async def my_subscription(request: Request, db: Session = Depends(get_db)):
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    return {
        "plan": getattr(user, "plan", None),
        "pro_expires_at": user.pro_expires_at.isoformat() if getattr(user, "pro_expires_at", None) else None
    }
