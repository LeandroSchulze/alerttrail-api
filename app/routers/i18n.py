# app/routers/i18n.py
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from urllib.parse import urlparse

router = APIRouter()

def _resolve_target(request: Request, next: str | None) -> str:
    target = (next or "").strip()

    if not target:
        ref = request.headers.get("referer") or ""
        try:
            u = urlparse(ref)
            target = (u.path or "") + (("?" + u.query) if u.query else "")
        except Exception:
            target = ""

    if not target or not target.startswith("/"):
        target = "/dashboard"
    return target

def _set_cookie_and_redirect(target: str, lang: str):
    lang = (lang or "es").lower()
    if lang not in ("es", "en"):
        lang = "es"

    resp = RedirectResponse(url=target, status_code=303)
    resp.set_cookie(
        "lang",
        lang,
        max_age=60 * 60 * 24 * 30,
        path="/",
        samesite="lax",
        httponly=False,
    )
    return resp

@router.get("/i18n/set", include_in_schema=False)
def set_lang_get(request: Request, lang: str = "es", next: str | None = None):
    target = _resolve_target(request, next)
    return _set_cookie_and_redirect(target, lang)

@router.post("/i18n/set", include_in_schema=False)
def set_lang_post(
    request: Request,
    lang: str = Form("es"),
    next: str | None = Form(None),
):
    target = _resolve_target(request, next)
    return _set_cookie_and_redirect(target, lang)
