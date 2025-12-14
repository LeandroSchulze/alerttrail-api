# app/routers/billing_ui.py
from __future__ import annotations

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user_cookie
from app.security import normalize_user_plan

router = APIRouter(tags=["billing-ui"])

@router.get("/upgrade", response_class=HTMLResponse, include_in_schema=False)
def upgrade_page(request: Request, db: Session = Depends(get_db), current=Depends(get_current_user_cookie)):
    user: User | None = db.query(User).filter(User.id == current["sub"]).first()
    if user:
        user = normalize_user_plan(db, user)

    templates = getattr(request.app.state, "templates", None)
    if templates is None:
        return HTMLResponse("<h1>Upgrade</h1><p>Templates no disponibles.</p>")

    try:
        return templates.TemplateResponse("upgrade.html", {"request": request, "current_user": user})
    except Exception:
        return HTMLResponse("<h1>Upgrade</h1><p>No encontré upgrade.html</p>")
