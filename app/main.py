# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.ui import templates
from app.i18n import get_lang_from_request, jinja_t, set_lang_cookie
from app.security import get_current_user_cookie

from app.database import SessionLocal
from app import models

# Routers
from app.routers import auth, analysis, mail, admin
from app.routers import alerts, billing, tools, reports

app = FastAPI(title="AlertTrail API")

# Static
app.mount("/static", StaticFiles(directory="app/static"), name="static")
# IMPORTANT: acá se sirven los PDFs generados como archivos estáticos
app.mount("/reports", StaticFiles(directory="app/reports"), name="reports")

# Routers
app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(mail.router)
app.include_router(admin.router)
app.include_router(alerts.router)
app.include_router(tools.router)
app.include_router(billing.router)
app.include_router(reports.router)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/set-lang/{lang}", include_in_schema=False)
def set_lang(lang: str, next: str = "/dashboard"):
    """Set language cookie and redirect.

    Path variant: /set-lang/en?next=/dashboard
    """
    resp = RedirectResponse(url=next or "/dashboard", status_code=302)
    set_lang_cookie(resp, lang)
    return resp


@app.get("/set-lang", include_in_schema=False)
def set_lang_q(lang: str = "es", next: str = "/dashboard"):
    """Compatibility: /set-lang?lang=en&next=/dashboard"""
    resp = RedirectResponse(url=next or "/dashboard", status_code=302)
    set_lang_cookie(resp, lang)
    return resp


@app.get("/dashboard")
def dashboard(request: Request):
    try:
        user = get_current_user_cookie(request)
    except Exception:
        return RedirectResponse(url="/auth/login", status_code=302)

    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    # Enrich user info from DB (plan/is_pro/is_admin) so the UI can show the real plan.
    db = SessionLocal()
    try:
        db_user = None
        try:
            uid = int(user.get("sub"))
        except Exception:
            uid = None

        if uid is not None:
            db_user = db.query(models.User).filter(models.User.id == uid).first()

        # Defaults
        plan = "FREE"
        is_admin = False

        if db_user is not None:
            is_admin = bool(getattr(db_user, "is_admin", False))
            is_pro = bool(getattr(db_user, "is_pro", False))
            db_plan = (getattr(db_user, "plan", "") or "").upper()

            # Admin siempre PRO
            if is_admin:
                plan = "PRO"
            else:
                plan = "PRO" if (is_pro or db_plan == "PRO") else "FREE"

            # Mejorar nombre/email si viene vacío en token
            if not user.get("name") and getattr(db_user, "name", None):
                user["name"] = db_user.name
            if not user.get("email") and getattr(db_user, "email", None):
                user["email"] = db_user.email

        user["plan"] = plan
        user["is_admin"] = is_admin
    finally:
        db.close()

    lang = get_lang_from_request(request)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "lang": lang,
            "t": jinja_t,
        },
    )
