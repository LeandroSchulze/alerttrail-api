from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from calendar import monthrange

from app.database import SessionLocal
from app.security import get_current_user_cookie
from app.models import User, PDFReport  # PDFReport: id, user_id, path, created_at
# Si tus modelos tienen otros nombres/campos, te los adapto.

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def require_admin(user: User):
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Solo admin")

@router.get("/stats")
def stats(db: Session = Depends(get_db), current=Depends(get_current_user_cookie)):
    require_admin(current)

    # Rango del mes actual (UTC)
    now = datetime.utcnow()
    start_month = datetime(year=now.year, month=now.month, day=1)
    last_day = monthrange(now.year, now.month)[1]
    end_month = datetime(year=now.year, month=now.month, day=last_day, hour=23, minute=59, second=59)

    # PDFs del mes
    pdfs_mes = db.query(PDFReport).filter(PDFReport.created_at >= start_month, PDFReport.created_at <= end_month).count()

    # Usuarios por plan
    usuarios_free = db.query(User).filter(User.plan == "FREE").count()
    usuarios_pro = db.query(User).filter(User.plan == "PRO").count()

    return {
        "pdfs_mes": pdfs_mes,
        "usuarios_free": usuarios_free,
        "usuarios_pro": usuarios_pro,
        "desde": start_month.isoformat(),
        "hasta": end_month.isoformat(),
    }
