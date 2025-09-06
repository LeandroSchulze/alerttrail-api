from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.security import get_current_user
from app import models

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/metrics")
def metrics(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if user.plan != "PRO":
        raise HTTPException(status_code=403, detail="Solo Pro por ahora")

    total_pdfs = db.query(models.Analysis).filter(models.Analysis.pdf_path.isnot(None)).count()
    users_pro = db.query(models.User).filter(models.User.plan == "PRO").count()

    per_month = (
        db.query(func.strftime('%Y-%m', models.Analysis.created_at), func.count(models.Analysis.id))
        .group_by(func.strftime('%Y-%m', models.Analysis.created_at))
        .all()
    )
    return {
        "pdf_reports": total_pdfs,
        "users_pro": users_pro,
        "analyses_per_month": {k: v for k, v in per_month},
    }
