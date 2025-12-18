from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse

from app.security import get_current_user_cookie
from app.ui import templates
from app.i18n import get_lang, t

router = APIRouter(prefix="", tags=["alerts"])

@router.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, user=Depends(get_current_user_cookie)):
    lang = get_lang(request)
    return templates.TemplateResponse("alerts.html", {
        "request": request, "lang": lang, "t": t, "current_user": user
    })
