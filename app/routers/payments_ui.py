# app/routers/payments_ui.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.database import get_db
from app.security import get_current_user_cookie

router = APIRouter(tags=["payments-ui"])

@router.get("/billing/payments", response_class=HTMLResponse, include_in_schema=False)
def payments_page(
    request: Request,
    db=Depends(get_db),
    user=Depends(get_current_user_cookie),
):
    """
    Página HTML que lista los últimos pagos.
    El front consulta /billing/history para los datos.
    """
    return request.app.state.templates.TemplateResponse(
        "payments.html",
        {
            "request": request,
            "user": user,
            "page_title": "Últimos pagos | AlertTrail",
        },
    )
