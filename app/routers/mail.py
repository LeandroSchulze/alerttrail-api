# app/routers/mail.py
import os, json
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.security import get_current_user_cookie
from app.ui import templates
from app.i18n import get_lang, t

router = APIRouter(prefix="/mail", tags=["mail"])

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKED_FILE = MAIL_DATA_DIR / "linked_accounts.json"


def _load_linked() -> Dict[str, Any]:
    if not LINKED_FILE.exists():
        return {}
    try:
        return json.loads(LINKED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_linked(data: Dict[str, Any]) -> None:
    MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    LINKED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _defaults_from_env() -> Dict[str, Any]:
    return {
        "server": os.getenv("IMAP_SERVER", ""),
        "port": int(os.getenv("IMAP_PORT", "993")),
        "folder": os.getenv("IMAP_FOLDER", "INBOX"),
        "use_ssl": os.getenv("IMAP_SSL", "1") in ("1", "true", "yes", "on"),
        "mark_read": os.getenv("IMAP_MARK_READ", "0") in ("1", "true", "yes", "on"),
    }


def _compute_plan(user: Dict[str, Any]) -> str:
    role = (user or {}).get("role") or ""
    if str(role).lower() == "admin":
        try:
            user["plan"] = "PRO"
        except Exception:
            pass
        return "PRO"
    return (user or {}).get("plan") or "FREE"


def get_user(request: Request):
    return get_current_user_cookie(request)


@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_user)):
    lang = get_lang(request)
    plan = _compute_plan(user)
    linked = None
    if user:
        linked = _load_linked().get(str(user.get("sub")))
    return templates.TemplateResponse(
        "mail.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "current_user": user,
            "user": user,
            "plan": plan,
            "defaults": _defaults_from_env(),
            "linked": linked,
        },
    )


@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_user)):
    lang = get_lang(request)
    plan = _compute_plan(user)
    linked = None
    if user:
        linked = _load_linked().get(str(user.get("sub")))
    return templates.TemplateResponse(
        "mail_scanner.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "current_user": user,
            "user": user,
            "plan": plan,
            "defaults": _defaults_from_env(),
            "linked": linked,
        },
    )


# -------------------------------------------------------------------
# Compat: /mail/settings (GET) redirige a /mail
# -------------------------------------------------------------------
@router.get("/settings", include_in_schema=False)
def mail_settings_compat():
    return RedirectResponse(url="/mail", status_code=302)


# -------------------------------------------------------------------
# Guardar configuración IMAP
# - Acepta distintos names de form (robusto ante cambios de template)
# -------------------------------------------------------------------
@router.post("/settings", include_in_schema=False)
async def save_mail_settings(
    request: Request,
    user=Depends(get_user),

    # "names" más comunes (opcionales)
    email: Optional[str] = Form(None),
    server: Optional[str] = Form(None),
    port: Optional[int] = Form(None),
    username: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    folder: Optional[str] = Form(None),
    use_ssl: Optional[str] = Form(None),
    mark_read: Optional[str] = Form(None),

    # aliases típicos (por si el template usa otros)
    imap_email: Optional[str] = Form(None),
    imap_server: Optional[str] = Form(None),
    imap_port: Optional[int] = Form(None),
    imap_user: Optional[str] = Form(None),
    imap_username: Optional[str] = Form(None),
    imap_password: Optional[str] = Form(None),
    imap_folder: Optional[str] = Form(None),
    imap_ssl: Optional[str] = Form(None),
    imap_mark_read: Optional[str] = Form(None),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    # Si algo vino vacío, leemos todo el form crudo y buscamos claves
    form = {}
    try:
        form = dict(await request.form())
    except Exception:
        form = {}

    def pick(*keys: str) -> Optional[str]:
        for k in keys:
            v = form.get(k)
            if v is not None and str(v).strip() != "":
                return str(v)
        return None

    def pick_int(*keys: str) -> Optional[int]:
        v = pick(*keys)
        if v is None:
            return None
        try:
            return int(float(v))
        except Exception:
            return None

    # Resolve valores finales (prioridad: params -> aliases -> form raw -> defaults)
    final_email = (email or imap_email or pick("email", "imap_email")).strip() if (email or imap_email or pick("email", "imap_email")) else ""
    final_server = (server or imap_server or pick("server", "imap_server")).strip() if (server or imap_server or pick("server", "imap_server")) else ""
    final_port = port or imap_port or pick_int("port", "imap_port")
    final_username = (username or imap_user or imap_username or pick("username", "imap_user", "imap_username")).strip() if (username or imap_user or imap_username or pick("username", "imap_user", "imap_username")) else ""
    final_password = password or imap_password or pick("password", "imap_password")
    final_folder = (folder or imap_folder or pick("folder", "imap_folder") or "INBOX").strip() or "INBOX"

    # Checkboxes: si existe el campo viene "on" o similar
    ssl_raw = use_ssl or imap_ssl or form.get("use_ssl") or form.get("imap_ssl")
    mark_raw = mark_read or imap_mark_read or form.get("mark_read") or form.get("imap_mark_read")

    # Defaults si falta algo
    defaults = _defaults_from_env()
    if not final_port:
        final_port = int(defaults["port"])
    if not final_server:
        final_server = str(defaults["server"] or "")
    if not final_folder:
        final_folder = str(defaults["folder"] or "INBOX")

    # Validación mínima (para evitar 422 y dar feedback claro)
    if not final_email or not final_server or not final_username or not final_password:
        # si querés, podés renderizar mail.html con error visible
        return {
            "ok": False,
            "error": "Faltan campos requeridos",
            "missing": {
                "email": not bool(final_email),
                "server": not bool(final_server),
                "username": not bool(final_username),
                "password": not bool(final_password),
            },
            "hint": "Revisá que el <form> tenga name=email, server, username, password (o aliases imap_*)",
        }

    # Gmail App Password suele venir con espacios
    password_clean = (final_password or "").replace(" ", "")

    data = _load_linked()
    data[str(user["sub"])] = {
        "email": final_email,
        "server": final_server,
        "port": int(final_port),
        "username": final_username,
        "password": password_clean,
        "folder": final_folder,
        "use_ssl": bool(ssl_raw),
        "mark_read": bool(mark_raw),
    }
    _save_linked(data)

    return RedirectResponse(url="/mail", status_code=302)


# Alias por si el template hace POST a /mail/link
@router.post("/link", include_in_schema=False)
async def save_mail_settings_link_alias(request: Request, user=Depends(get_user)):
    return await save_mail_settings(request=request, user=user)
