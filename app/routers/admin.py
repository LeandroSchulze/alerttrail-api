from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..deps import get_current_user, get_db
from ..models import User, DownloadMetric, PlanEnum

router = APIRouter(prefix="/admin", tags=["admin"])

def require_admin(user: User):
    if user.email != "admin@example.com":
        raise HTTPException(403, "Solo admin")

@router.get("/stats")
def stats(db: Session = Depends(get_db), user=Depends(get_current_user)):
    require_admin(user)
    pro_users = db.query(User).filter(User.plan == PlanEnum.PRO).count()
    downloads = db.query(DownloadMetric).all()
    return {"pro_users": pro_users, "downloads": [{"month": d.month_key, "count": d.count} for d in downloads]}
