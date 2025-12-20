# app/routers/mail.py
import os
import json
import imaplib
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from app.security import get_current_user_cookie
from app.ui import templates
from app.i18n import get_lang, t

router = APIRouter(prefix="/mail", tags=["mail"])

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKED_FILE = MAIL_DATA_DIR / "linked_accounts.json"


# ----------------------------
# Helpers persistencia
# ----------------------------
def _load_linked_all() -> Dict[str, Any]:
    if not LINKED_FILE.exists():
        return {}
    try:
        return json.loads(LINKED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_linked_all(data: Dict[str, Any]) -> None:
    LINKED_FILE.parent.mkdir(parents=True, exist_ok=True)
    LINKED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_user_id(user: Dict[str, Any]) -> str:
    # en tu app venís usando sub en el token
    return str(user.get("sub") or user.get("id") or "")


def _defaults_from_env() -> Dict[str, Any]:
    return {
        "server": os.getenv("IMAP_SERVER", "imap.gmail.com"),
        "port": int(os.getenv("IMAP_PORT", "993")),
        "folder": os.getenv("IMAP_FOLDER", "INBOX"),
        "use_ssl": os.getenv("IMAP_SSL", "1").lower() in ("1", "true", "yes", "on"),
        "mark_read": os.getenv("IMAP_MARK_READ", "0").lower() in ("1", "true", "yes", "on"),
    }


def _compute_plan(user: Dict[str, Any]) -> str:
    role = (user or {}).get("role") or ""
    if str(role).lower() == "admin":
        # admin = pro
        try:
            user["plan"] = "PRO"
        except Exception:
            pass
        return "PRO"
    return (user or {}).get("plan") or "FREE"


def get_user(request: Request):
    return get_current_user_cookie(request)


def _parse_bool(v: Optional[str], default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _parse_int(v: Optional[str], default: int) -> int:
    try:
        if v is None or str(v).strip() == "":
            return default
        return int(str(v).strip())
    except Exception:
        return default


# ----------------------------
# Pages
# ----------------------------
@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_user)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)
    plan = _compute_plan(user)
    linked = _load_linked_all().get(_get_user_id(user))

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
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)
    plan = _compute_plan(user)
    linked = _load_linked_all().get(_get_user_id(user))

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


# compat: si alguien entra a /mail/settings por URL vieja
@router.get("/settings", include_in_schema=False)
def mail_settings_compat():
    return RedirectResponse(url="/mail", status_code=302)


# ----------------------------
# Save settings (form POST)
# ----------------------------
@router.post("/settings", include_in_schema=False)
async def save_mail_settings(request: Request, user=Depends(get_user)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    form = await request.form()

    # Soportamos DOS naming conventions:
    # 1) "email/server/username/password/port/folder/use_ssl/mark_read"
    # 2) "imap_email/imap_server/imap_username/imap_password/imap_port/imap_folder/imap_ssl/imap_mark_read"
    email = (form.get("email") or form.get("imap_email") or "").strip()
    server = (form.get("server") or form.get("imap_server") or "").strip()

    username = (form.get("username") or form.get("imap_username") or "").strip()
    password = (form.get("password") or form.get("imap_password") or "")

    # defaults si faltan
    defaults = _defaults_from_env()
    port = _parse_int(form.get("port") or form.get("imap_port"), defaults["port"])
    folder = (form.get("folder") or form.get("imap_folder") or defaults["folder"]).strip() or "INBOX"

    use_ssl = _parse_bool(form.get("use_ssl") or form.get("imap_ssl"), defaults["use_ssl"])
    mark_read = _parse_bool(form.get("mark_read") or form.get("imap_mark_read"), defaults["mark_read"])

    missing = {
        "email": not bool(email),
        "server": not bool(server),
        "username": not bool(username),
        "password": not bool(password),
    }
    if any(missing.values()):
        # devolvemos JSON friendly para debug (lo viste en tu screenshot)
        return HTMLResponse(
            json.dumps(
                {
                    "ok": False,
                    "error": "Faltan campos requeridos",
                    "missing": missing,
                    "hint": "Revisá que el <form> tenga name=email, server, username, password (o aliases imap_*)",
                },
                ensure_ascii=False,
            ),
            status_code=422,
            media_type="application/json",
        )

    uid = _get_user_id(user)
    if not uid:
        return HTMLResponse(
            json.dumps({"ok": False, "error": "Usuario inválido"}, ensure_ascii=False),
            status_code=400,
            media_type="application/json",
        )

    all_linked = _load_linked_all()
    all_linked[uid] = {
        "email": email,
        "server": server,
        "port": int(port),
        "username": username,
        "password": password,
        "folder": folder,
        "use_ssl": bool(use_ssl),
        "mark_read": bool(mark_read),
    }
    _save_linked_all(all_linked)

    # volvemos al /mail (o a donde venga next)
    next_url = (form.get("next") or "/mail").strip() or "/mail"
    return RedirectResponse(url=next_url, status_code=303)


# ----------------------------
# Scan endpoint (basic IMAP)
# ----------------------------
@router.get("/scan", include_in_schema=False)
def mail_scan(request: Request, user=Depends(get_user)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    uid = _get_user_id(user)
    all_linked = _load_linked_all()
    cfg = all_linked.get(uid)

    if not cfg:
        return HTMLResponse(
            "<h3>No hay configuración IMAP guardada</h3><p>Volvé a /mail y guardá la config primero.</p>",
            status_code=400,
        )

    server = cfg.get("server")
    port = int(cfg.get("port") or 993)
    username = cfg.get("username")
    password = cfg.get("password")
    folder = cfg.get("folder") or "INBOX"
    use_ssl = bool(cfg.get("use_ssl", True))

    try:
        if use_ssl:
            imap = imaplib.IMAP4_SSL(server, port)
        else:
            imap = imaplib.IMAP4(server, port)

        imap.login(username, password)

        # seleccionar carpeta
        typ, _ = imap.select(folder)
        if typ != "OK":
            imap.logout()
            return HTMLResponse(
                f"<h3>No pude abrir la carpeta IMAP: {folder}</h3><a href='/mail/scanner'>Volver</a>",
                status_code=400,
            )

        # por ahora: contar emails
        typ, data = imap.search(None, "ALL")
        if typ != "OK":
            imap.logout()
            return HTMLResponse(
                "<h3>No pude listar correos (IMAP search)</h3><a href='/mail/scanner'>Volver</a>",
                status_code=400,
            )

        ids = data[0].split() if data and data[0] else []
        count = len(ids)

        imap.logout()

        # Mostrar un resultado simple y volver
        return HTMLResponse(
            f"""
            <div style="font-family:system-ui;padding:24px">
              <h2>Scan IMAP OK ✅</h2>
              <p>Servidor: <strong>{server}</strong></p>
              <p>Carpeta: <strong>{folder}</strong></p>
              <p>Correos encontrados: <strong>{count}</strong></p>
              <a href="/mail/scanner">← Volver al scanner</a>
            </div>
            """,
            status_code=200,
        )

    except imaplib.IMAP4.error as e:
        # errores típicos: AUTHENTICATIONFAILED
        return HTMLResponse(
            f"""
            <div style="font-family:system-ui;padding:24px">
              <h2>Error IMAP ❌</h2>
              <pre>{str(e)}</pre>
              <p>Tip Gmail: asegurate de usar <strong>App Password</strong> (16 caracteres) y que el usuario sea el email completo.</p>
              <a href="/mail/scanner">← Volver</a>
            </div>
            """,
            status_code=500,
        )
    except Exception as e:
        return HTMLResponse(
            f"""
            <div style="font-family:system-ui;padding:24px">
              <h2>Error inesperado ❌</h2>
              <pre>{str(e)}</pre>
              <a href="/mail/scanner">← Volver</a>
            </div>
            """,
            status_code=500,
        )
