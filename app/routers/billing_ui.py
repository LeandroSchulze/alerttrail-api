# app/routers/billing_ui.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.database import get_db
from app.security import get_current_user_cookie

router = APIRouter(tags=["billing-ui"])

@router.get("/account/billing", response_class=HTMLResponse, response_model=None)
def billing_page(
    request: Request,
    db = Depends(get_db),                  # <- sin type hints
    user = Depends(get_current_user_cookie),  # <- sin type hints
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
