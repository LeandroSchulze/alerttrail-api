# app/routers/stats_ui.py
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.security import get_current_user_cookie

router = APIRouter(prefix="/stats", tags=["stats-ui"])

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def stats_home(request: Request, user=Depends(get_current_user_cookie)):
    # Render básico; tu template es admin_stats.html
    return request.app.state.templates.TemplateResponse(
        "admin_stats.html", {"request": request, "user": user, "page_title": "Estadísticas"}
    )
