# app/routers/billing_ui.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import get_current_user_cookie
from app.models import User

router = APIRouter(tags=["billing-ui"])

@router.get("/account/billing", response_class=HTMLResponse)
def billing_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_cookie),
):
    """
    Página de Suscripción/Facturación (UI). Requiere sesión.
    Carga datos con fetch a /billing/me y /billing/history.
    """
    # Renderiza plantilla Jinja (usa request.state.templates si ya lo manejas así)
    # Si usas Jinja2Templates en main.py como templates = Jinja2Templates(directory="app/templates"):
    return request.app.state.templates.TemplateResponse(
        "billing.html",
        {
            "request": request,
            "user": user,
            "page_title": "Mi Suscripción | AlertTrail",
        },
    )
