from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from pathlib import Path

from app.ui import templates
from app.security import get_current_user_cookie

router = APIRouter(prefix="/reports_browser", tags=["reports"])

REPORTS_DIR = Path("app/reports")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def reports_browser(request: Request, current=Depends(get_current_user_cookie)):
    if current is None:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Please login"},
            status_code=401,
        )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted([p.name for p in REPORTS_DIR.glob("*.pdf")], reverse=True)

    # los PDFs se sirven como /reports/<archivo>.pdf por StaticFiles
    return templates.TemplateResponse(
        "reports.html",
        {"request": request, "files": files},
    )
