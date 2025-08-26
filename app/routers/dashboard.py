from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from ..deps import get_current_user, get_db
from ..models import Analysis

router = APIRouter(tags=["ui"])

@router.get("/dashboard", response_class=HTMLResponse)
def home(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    latest = db.query(Analysis).filter(Analysis.user_id==user.id).order_by(Analysis.created_at.desc()).limit(5).all()
    return request.app.state.templates.TemplateResponse("dashboard.html", {"request": request, "user": user, "latest": latest})
