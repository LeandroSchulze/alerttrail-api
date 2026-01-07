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

    # 2) si no, intentamos referer
    if not target:
        ref = request.headers.get("referer") or ""
        try:
            u = urlparse(ref)
            target = (u.path or "") + (("?" + u.query) if u.query else "")
        except Exception:
            target = ""

    # 3) fallback
    if not target or not target.startswith("/"):
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
