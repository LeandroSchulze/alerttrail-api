# app/routers/stats_ui.py
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.database import get_db
from app.security import get_current_user_cookie

router = APIRouter(tags=["stats-ui"])

@router.get("/stats", response_class=HTMLResponse, include_in_schema=False)
def stats_page(request: Request, db=Depends(get_db), user=Depends(get_current_user_cookie)):
    """
    Página de estadísticas con datos de descargas, usuarios y análisis.
    """
    return request.app.state.templates.TemplateResponse(
        "admin_stats.html",
        {"request": request, "user": user, "page_title": "Estadísticas | AlertTrail"},
    )
