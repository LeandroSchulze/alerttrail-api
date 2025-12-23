# app/routers/tools.py
from __future__ import annotations

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from app.security import get_current_user_cookie
from app.ui import templates
from app.i18n import get_lang, t

# ✅ Plan guard
from app.plan_guard import get_current_user_db

router = APIRouter(prefix="/tools", tags=["tools"])


def _require_pro_or_redirect(request: Request):
    """
    - No logueado -> login
    - Free -> upgrade
    - Pro/Admin -> ok
    """
    try:
        cu = get_current_user_db(request)  # valida cookie + user DB
    except Exception:
        return None, RedirectResponse(url="/auth/login", status_code=302)

    if not cu.is_pro:
        nxt = request.url.path
        return None, RedirectResponse(url=f"/billing/subscriptions?next={nxt}", status_code=302)

    return cu, None


@router.get("/qr-scan", response_class=HTMLResponse)
def qr_scan(request: Request, user=Depends(get_current_user_cookie)):
    lang = get_lang(request)

    cu, redir = _require_pro_or_redirect(request)
    if redir:
        return redir

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

    cu, redir = _require_pro_or_redirect(request)
    if redir:
        return redir

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
