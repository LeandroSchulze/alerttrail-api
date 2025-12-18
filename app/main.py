# app/main.py
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

# Seguridad (cookie JWT)
from app.security import get_current_user_cookie

# i18n (ajustá estos imports si tu módulo usa otro nombre)
# La idea es que existan: get_lang_from_request(request) -> "es"/"en"
#                        set_lang_cookie(response, "es"/"en")
#                        jinja_t(lang, key, **kwargs) -> str
from app.i18n import get_lang_from_request, set_lang_cookie, jinja_t

# Routers (ajustá los que existan en tu proyecto)
from app.routers import auth, analysis, mail, admin
# si tenés org/payments/push, agregalos:
# from app.routers import org, payments, push


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def _reports_dir() -> Path:
    # Ideal para Render: /var/data/reports
    return Path(os.getenv("REPORTS_DIR", str(BASE_DIR / ".." / "reports"))).resolve()


app = FastAPI(title="AlertTrail", version="1.0.0")

# -------------------------
# Templates (CLAVE para auth.py)
# -------------------------
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Exponemos helpers a Jinja
templates.env.globals["t"] = jinja_t  # en Jinja vas a usar: {{ t(lang, "key") }}
templates.env.globals["jinja_t"] = jinja_t

# Guardamos templates en app.state para que los routers NO importen main.py
app.state.templates = templates


# -------------------------
# Static + Reports
# -------------------------
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

REPORTS_DIR = _reports_dir()
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")


# -------------------------
# Middleware simple: lang en request.state
# -------------------------
@app.middleware("http")
async def lang_middleware(request: Request, call_next):
    lang = get_lang_from_request(request) or "es"
    request.state.lang = lang
    response = await call_next(request)
    return response


# -------------------------
# Rutas base
# -------------------------
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def root():
    # Si hay sesión, al dashboard; si no, al login
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/login")
def login_alias():
    # Alias para evitar 404 si algún redirect viejo apunta a /login
    return RedirectResponse(url="/auth/login", status_code=302)


@app.get("/set-lang/{lang}")
def set_lang(lang: str, request: Request):
    # Alternativa simple para toggle (si ya tenés una ruta en auth.py, podés borrar esto)
    if lang not in ("es", "en"):
        lang = "es"
    resp = RedirectResponse(url=request.headers.get("referer", "/dashboard"), status_code=302)
    set_lang_cookie(resp, lang)
    return resp


@app.get("/dashboard")
def dashboard(request: Request):
    user = get_current_user_cookie(request)

    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = getattr(request.state, "lang", "es")

    # IMPORTANTE:
    # Tu dashboard.html usa `user` y también a veces `current_user`.
    # Para evitar el error 'current_user is undefined', pasamos ambos.
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "lang": lang,
            "user": user,
            "current_user": user,
        },
    )


# -------------------------
# Routers
# -------------------------
# Auth (login web, API auth, logout, etc.)
app.include_router(auth.router)

# Resto (ajustá según tu proyecto)
app.include_router(analysis.router)
app.include_router(mail.router)
app.include_router(admin.router)

# si existen:
# app.include_router(org.router)
# app.include_router(payments.router)
# app.include_router(push.router)
