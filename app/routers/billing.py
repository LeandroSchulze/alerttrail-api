from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse

from app.security import get_current_user_cookie
from app.ui import templates
from app.i18n import get_lang, t

router = APIRouter(prefix="/billing", tags=["billing"])

@router.get("/subscriptions", response_class=HTMLResponse)
def subscriptions(request: Request, user=Depends(get_current_user_cookie)):
    lang = get_lang(request)
    return templates.TemplateResponse("billing_subscriptions.html", {
        "request": request, "lang": lang, "t": t, "current_user": user
    })

@router.get("/payments", response_class=HTMLResponse)
def payments(request: Request, user=Depends(get_current_user_cookie)):
    lang = get_lang(request)
    return templates.TemplateResponse("billing_payments.html", {
        "request": request, "lang": lang, "t": t, "current_user": user
    })
