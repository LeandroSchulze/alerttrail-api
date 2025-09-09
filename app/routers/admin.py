from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app import models
from app.security import get_current_user

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/metrics")
def metrics(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if user.plan != "PRO":
        return {"detail": "Solo Pro", "ok": False}
    total_pdfs = db.query(models.Analysis).filter(models.Analysis.pdf_path.isnot(None)).count()
    users_pro = db.query(models.User).filter(models.User.plan == "PRO").count()
    per_month = (
        db.query(func.strftime('%Y-%m', models.Analysis.created_at), func.count(models.Analysis.id))
        .group_by(func.strftime('%Y-%m', models.Analysis.created_at))
        .all()
    )
    return {"ok": True, "pdf_reports": total_pdfs, "users_pro": users_pro, "analyses_per_month": dict(per_month)}
