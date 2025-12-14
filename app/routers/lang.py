from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.i18n import SUPPORTED_LANGS, DEFAULT_LANG

router = APIRouter(tags=["lang"])


@router.get("/set-lang/{lang_code}")
def set_lang(lang_code: str, request: Request):
    """
    Ajusta cookie de idioma y redirige a la página anterior.
    """
    lang = lang_code if lang_code in SUPPORTED_LANGS else DEFAULT_LANG
    referer = request.headers.get("referer") or "/"
    resp = RedirectResponse(url=referer, status_code=303)
    resp.set_cookie(
        "alerttrail_lang",
        lang,
        max_age=60 * 60 * 24 * 365,  # 1 año
        httponly=False,  # tiene sentido que JS pueda leerla si la necesitás
        samesite="lax",
    )
    return resp
