from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from calendar import monthrange

from app.database import SessionLocal
from app.security import get_current_user_cookie
from app.models import User

# intenta detectar tu modelo de reportes
ReportModel = None
try:
    from app.models import PDFReport as ReportModel
except Exception:
    try:
        from app.models import Report as ReportModel
    except Exception:
        try:
            from app.models import Analysis as ReportModel
        except Exception:
            ReportModel = None

router = APIRouter()

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def require_admin(u: User):
    if not u or getattr(u, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Solo admin")

@router.get("/stats")
def stats(db: Session = Depends(get_db), current=Depends(get_current_user_cookie)):
    require_admin(current)
    now = datetime.utcnow()
    start = datetime(now.year, now.month, 1)
    end = datetime(now.year, now.month, monthrange(now.year, now.month)[1], 23, 59, 59)

    pdfs_mes = 0
    if ReportModel is not None and hasattr(ReportModel, "created_at"):
        pdfs_mes = db.query(ReportModel).filter(ReportModel.created_at >= start, ReportModel.created_at <= end).count()

    usuarios_free = db.query(User).filter(User.plan == "FREE").count()
    usuarios_pro = db.query(User).filter(User.plan == "PRO").count()

    return {"pdfs_mes": pdfs_mes, "usuarios_free": usuarios_free, "usuarios_pro": usuarios_pro,
            "desde": start.isoformat(), "hasta": end.isoformat()}


def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def require_admin(u: User):
    if not u or getattr(u, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Solo admin")

@router.get("/stats")
def stats(db: Session = Depends(get_db), current=Depends(get_current_user_cookie)):
    require_admin(current)
    now = datetime.utcnow()
    start = datetime(now.year, now.month, 1)
    end = datetime(now.year, now.month, monthrange(now.year, now.month)[1], 23, 59, 59)

    pdfs_mes = 0
    if ReportModel is not None and hasattr(ReportModel, "created_at"):
        pdfs_mes = db.query(ReportModel).filter(ReportModel.created_at >= start, ReportModel.created_at <= end).count()

    usuarios_free = db.query(User).filter(User.plan == "FREE").count()
    usuarios_pro = db.query(User).filter(User.plan == "PRO").count()

    return {"pdfs_mes": pdfs_mes, "usuarios_free": usuarios_free, "usuarios_pro": usuarios_pro,
            "desde": start.isoformat(), "hasta": end.isoformat()}
