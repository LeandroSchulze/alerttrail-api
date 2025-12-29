# app/routers/i18n.py
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from urllib.parse import urlparse

router = APIRouter()

@router.get("/i18n/set", include_in_schema=False)
def set_lang(request: Request, lang: str = "es", next: str | None = None):
    lang = (lang or "es").lower()
    if lang not in ("es", "en"):
        lang = "es"

    # 1) Si viene next explícito, lo usamos (preferido)
    target = (next or "").strip()

    # 2) Si no hay next, usamos referer pero sanitizado
    if not target:
        referer = (request.headers.get("referer") or "").strip()
        if referer:
            try:
                p = urlparse(referer)
                # nos quedamos solo con path + query (evita open redirects)
                target = p.path or "/dashboard"
                if p.query:
                    target = f"{target}?{p.query}"
            except Exception:
                target = "/dashboard"
        else:
            target = "/dashboard"

    # 3) Seguridad mínima: solo paths relativos internos
    if not target.startswith("/"):
        target = "/dashboard"

    # 4) Evitar loop infinito: si el target es este mismo endpoint, mandamos a dashboard
    if target.startswith("/i18n/set"):
        target = "/dashboard"

    resp = RedirectResponse(url=target, status_code=303)

    # 30 días
    resp.set_cookie(
        "lang",
        lang,
        max_age=60 * 60 * 24 * 30,
        path="/",
        samesite="lax",
        httponly=False,
    )
    return resp
