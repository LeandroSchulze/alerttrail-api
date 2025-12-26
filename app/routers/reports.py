# app/routers/reports.py
from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from app.ui import templates
from app.security import get_current_user_cookie_optional
from app.i18n import get_lang_from_request, jinja_t

router = APIRouter(prefix="/reports_browser", tags=["reports"])

REPORTS_DIR = Path("app/reports")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def reports_browser(request: Request, current=Depends(get_current_user_cookie_optional)):
    if not current:
        return RedirectResponse(url="/auth/login", status_code=302)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted([p.name for p in REPORTS_DIR.glob("*.pdf")], reverse=True)

    lang = get_lang_from_request(request)

    user = dict(current)
    user.setdefault("name", "User")
    user.setdefault("email", "")

    current_user = user

    return templates.TemplateResponse(
        "reports.html",
        {
            "request": request,
            "files": files,
            "user": user,
            "current_user": current_user,
            "lang": lang,
            "t": jinja_t,
            "plan": (user.get("plan") or "").upper(),
        },
    )
