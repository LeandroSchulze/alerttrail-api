from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from app.database import get_db
from app.security import get_current_user
from app import models, schemas

router = APIRouter(prefix="/history", tags=["history"])

@router.get("/list", response_model=List[schemas.AnalysisOut])
def list_history(
    start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    q = db.query(models.Analysis).filter(models.Analysis.user_id == user.id)
    if start:
        q = q.filter(models.Analysis.created_at >= datetime.fromisoformat(start))
    if end:
        q = q.filter(models.Analysis.created_at <= datetime.fromisoformat(end))
    q = q.order_by(models.Analysis.created_at.desc())
    return q.all()
