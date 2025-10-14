from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import get_current_user_cookie

router = APIRouter(prefix="/subscription", tags=["subscription"])

@router.get("/me")
async def my_subscription(db: Session = Depends(get_db), current_user=Depends(get_current_user_cookie)):
    return {
        "plan": current_user.plan,
        "pro_expires_at": current_user.pro_expires_at.isoformat() if current_user.pro_expires_at else None
    }
