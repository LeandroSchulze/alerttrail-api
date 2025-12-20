# app/routers/reports.py
from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from app.ui import templates
from app.security import get_current_user_cookie
from app.i18n import get_lang_from_request, jinja_t

router = APIRouter(prefix="/reports_browser", tags=["reports"])

REPORTS_DIR = Path("app/reports")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def reports_browser(request: Request, current=Depends(get_current_user_cookie)):
    # Si no hay sesión, mandamos al login real
    if not current:
        return RedirectResponse(url="/auth/login", status_code=302)

    # Asegurar carpeta (en Render puede no existir)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Listar PDFs
    files = sorted([p.name for p in REPORTS_DIR.glob("*.pdf")], reverse=True)

    # i18n / helpers para que el template no explote
    lang = get_lang_from_request(request)

    # Normalizar "user" para que sea consistente con el resto de templates
    user = dict(current)
    # defaults por si el token vino incompleto
    user.setdefault("name", "User")
    user.setdefault("email", "")

    # Compat: algunos templates usan current_user
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
