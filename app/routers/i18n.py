# app/routers/i18n.py
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter()

@router.get("/i18n/set", include_in_schema=False)
def set_lang(request: Request, lang: str = "es"):
    lang = (lang or "es").lower()
    if lang not in ("es", "en"):
        lang = "es"

    # Volvemos a la página anterior o al dashboard
    referer = request.headers.get("referer") or "/dashboard"

    resp = RedirectResponse(url=referer, status_code=303)
    # 30 días
    resp.set_cookie(
        "lang",
        lang,
        max_age=60 * 60 * 24 * 30,
        path="/",
        samesite="Lax",
        httponly=False,
    )
    return resp
