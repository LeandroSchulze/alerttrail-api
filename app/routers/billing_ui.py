# app/routers/billing_ui.py
from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import get_current_user_cookie
from app.models import User

router = APIRouter(tags=["billing-ui"])

DbDep = Annotated[Session, Depends(get_db)]
UserDep = Annotated[User, Depends(get_current_user_cookie)]

@router.get("/account/billing", response_class=HTMLResponse, response_model=None)
def billing_page(
    request: Request,
    db: DbDep,          # Annotated evita el error con Pydantic v2
    user: UserDep,      # Igual acá
):
    """
    Página de Suscripción/Facturación (UI). Requiere sesión.
    Carga datos con fetch a /billing/me y /billing/history.
    """
    return request.app.state.templates.TemplateResponse(
        "billing.html",
        {
            "request": request,
            "user": user,
            "page_title": "Mi Suscripción | AlertTrail",
        },
    )
