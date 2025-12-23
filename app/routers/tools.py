# app/routers/tools.py
from __future__ import annotations

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse

from app.security import get_current_user_cookie
from app.ui import templates
from app.i18n import get_lang, t

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/qr-scan", response_class=HTMLResponse)
def qr_scan(request: Request, user=Depends(get_current_user_cookie)):
    lang = get_lang(request)
    return templates.TemplateResponse(
        "tools_qr.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "current_user": user,
            "user": user,
        },
    )


@router.get("/receipt-analyzer", response_class=HTMLResponse)
def receipt_analyzer(request: Request, user=Depends(get_current_user_cookie)):
    lang = get_lang(request)
    return templates.TemplateResponse(
        "tools_receipt.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "current_user": user,
            "user": user,
        },
    )
