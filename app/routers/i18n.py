# app/routers/i18n.py
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter()

@router.get("/i18n/set")
async def set_language(request: Request, lang: str = "es"):
    """
    Setea cookie de idioma y redirige de vuelta.
    """
    # Solo permitir idiomas válidos
    if lang.lower() not in ("es", "en"):
        lang = "es"

    referer = request.headers.get("referer") or "/dashboard"
    resp = RedirectResponse(url=referer, status_code=303)
    resp.set_cookie(
        key="lang",
        value=lang.lower(),
        max_age=60 * 60 * 24 * 365,  # 1 año
        path="/",
        samesite="Lax",
        secure=True,
        httponly=False  # para que el frontend pueda leerlo si lo necesita
    )
    return resp
