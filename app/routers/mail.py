from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
import os, json, imaplib
from pathlib import Path

from app.security import get_current_user_cookie

router = APIRouter(prefix="/mail", tags=["mail"])

# Archivo plano para guardar estado por usuario
DATA_DIR = Path(os.getenv("DATA_DIR", "/var/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LINK_FILE = DATA_DIR / "mail_link.json"  # mantiene compatibilidad (misma ruta)

# ---------------- utils ----------------
def _env_bool(v, default=False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}

def _load_all() -> dict:
    if LINK_FILE.exists():
        try:
            return json.loads(LINK_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_all(data: dict):
    LINK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _get_user_entry(uid: str) -> dict:
    all_ = _load_all()
    return all_.get(uid, {})

def _set_user_entry(uid: str, entry: dict):
    all_ = _load_all()
    all_[uid] = entry
    _save_all(all_)

def _defaults_from_env():
    return dict(
        host=os.getenv("MAIL_HOST", "imap.gmail.com"),
        port=int(os.getenv("MAIL_PORT", "993") or 993),
        use_ssl=_env_bool(os.getenv("MAIL_USE_SSL", "true"), True),
        username=os.getenv("MAIL_USERNAME", ""),
        folder=os.getenv("MAIL_FOLDER", "INBOX") or "INBOX",
        mark_seen=_env_bool(os.getenv("MAIL_MARK_SEEN", "false"), False),
    )

def _resolve_cfg(uid: str):
    """
    Mezcla configuración guardada por usuario (si existe) con los valores por ENV.
    Prioriza lo guardado.
    """
    env = _defaults_from_env()
    entry = _get_user_entry(uid)
    cfg = entry.get("imap_cfg", {})
    # valores efectivos
    return dict(
        host=cfg.get("host", env["host"]),
        port=int(cfg.get("port", env["port"])),
        use_ssl=bool(cfg.get("use_ssl", env["use_ssl"])),
        username=cfg.get("username", env["username"]),
        password=cfg.get("password", os.getenv("MAIL_PASSWORD", "")),
        folder=cfg.get("folder", env["folder"]),
        mark_seen=bool(cfg.get("mark_seen", env["mark_seen"])),
    )

# ---------------- UI ----------------
@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_current_user_cookie)):
    uid = str(user["sub"])
    entry = _get_user_entry(uid)
    linked = {"address": entry.get("address")} if entry.get("address") else None
    env_defaults = _defaults_from_env()
    user_cfg = _resolve_cfg(uid)

    ctx = {
        "request": request,
        "page_title": "Casillas de correo",
        "current_user": user,
        "linked": linked,
        "defaults": env_defaults,
        "user_cfg": {
            **{k: v for k, v in user_cfg.items() if k != "password"},
            "has_password": bool(user_cfg.get("password")),
        },
    }
    # Template principal
    try:
        return request.app.state.templates.TemplateResponse("mail.html", ctx)
    except Exception:
        # Fallback mínimo con formulario
        pw_hint = "********" if user_cfg.get("password") else ""
        html = f"""
        <!doctype html><meta charset="utf-8">
        <div style="font-family:system-ui;padding:24px;max-width:720px;margin:auto">
          <h1>Casillas de correo</h1>
          <div style="border:1px solid #e5e7eb;border-radius:12px;padding:16px">
            <form method="post" action="/mail/connect" style="display:flex;gap:8px;align-items:center">
              <input name="address" type="email" placeholder="tu@dominio.com" value="{(linked or {}).get('address','')}" required style="flex:1;padding:8px">
              <button style="padding:8px 12px">{"Reemplazar" if linked else "Linkear"}</button>
              <a href="/mail/scanner" style="padding:8px 12px;border:1px solid #ccc;border-radius:8px;text-decoration:none">Abrir Scanner</a>
            </form>
            <hr style="margin:16px 0">
            <h3>Parámetros IMAP</h3>
            <form method="post" action="/mail/settings" style="display:grid;gap:8px">
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
                <input name="host" placeholder="Host IMAP" value="{user_cfg['host']}" required>
                <input name="port" placeholder="Puerto" type="number" value="{user_cfg['port']}" required>
                <label style="display:flex;align-items:center;gap:6px"><input type="checkbox" name="use_ssl" {"checked" if user_cfg['use_ssl'] else ""}> Usar SSL</label>
                <label style="display:flex;align-items:center;gap:6px"><input type="checkbox" name="mark_seen" {"checked" if user_cfg['mark_seen'] else ""}> Marcar como leído</label>
                <input name="folder" placeholder="Carpeta (INBOX)" value="{user_cfg['folder']}">
                <input name="username" placeholder="Usuario IMAP" value="{user_cfg['username']}">
                <input name="password" placeholder="Clave IMAP (app password)" value="{pw_hint}">
              </div>
              <button style="padding:8px 12px">Guardar</button>
              <small>El scanner usa estos valores primero. Si faltan, tomará los de las variables de entorno.</small>
            </form>
          </div>
        </div>
        """
        return HTMLResponse(html)

@router.post("/connect")
def mail_connect(address: str = Form(...), user=Depends(get_current_user_cookie)):
    address = (address or "").strip().lower()
    if not address or "@" not in address:
        raise HTTPException(status_code=400, detail="Dirección inválida")
    uid = str(user["sub"])
    entry = _get_user_entry(uid)
    entry["address"] = address
    _set_user_entry(uid, entry)
    return RedirectResponse(url="/mail", status_code=303)

@router.post("/settings")
def save_settings(
    request: Request,
    user=Depends(get_current_user_cookie),
    host: str = Form(...),
    port: int = Form(...),
    use_ssl: str | None = Form(None),
    username: str = Form(""),
    password: str = Form(""),
    folder: str = Form("INBOX"),
    mark_seen: str | None = Form(None),
):
    """
    Guarda configuración IMAP por usuario.
    - Si el campo password viene como "********", se mantiene el valor previo.
    """
    uid = str(user["sub"])
    entry = _get_user_entry(uid)
    cfg = entry.get("imap_cfg", {})

    keep_pwd = password.strip() == "********"
    new_cfg = {
        "host": (host or "").strip(),
        "port": int(port or 993),
        "use_ssl": bool(use_ssl is not None),
        "username": (username or "").strip(),
        "password": (cfg.get("password") if keep_pwd else (password or "")),
        "folder": (folder or "INBOX").strip() or "INBOX",
        "mark_seen": bool(mark_seen is not None),
    }
    entry["imap_cfg"] = new_cfg
    _set_user_entry(uid, entry)
    return RedirectResponse(url="/mail", status_code=303)

# ---- Scanner UI ----
@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_current_user_cookie)):
    uid = str(user["sub"])
    ctx = {
        "request": request,
        "page_title": "Mail Scanner",
        "current_user": user,
        "linked": {"address": _get_user_entry(uid).get("address")},
        "defaults": _defaults_from_env(),
        "user_cfg": _resolve_cfg(uid),
    }
    try:
        return request.app.state.templates.TemplateResponse("mail_scanner.html", ctx)
    except Exception:
        # Fallback simple
        return HTMLResponse(
            "<h1 style='font-family:system-ui;padding:24px'>Mail Scanner</h1>"
            "<p style='font-family:system-ui;padding:0 24px'>Usá el botón 'Ejecutar scan' en esta página (si existe en tu template) o probá /mail/scan.</p>"
        )

class ScanResult(BaseModel):
    ok: bool
    login: bool
    folder: str
    unread: int
    total: int
    marked_seen: bool
    message: str | None = None

@router.post("/scan", response_model=ScanResult)
def mail_scan(user=Depends(get_current_user_cookie)):
    uid = str(user["sub"])
    cfg = _resolve_cfg(uid)

    host = cfg["host"]
    port = int(cfg["port"])
    use_ssl = bool(cfg["use_ssl"])
    username = cfg["username"]
    password = cfg["password"]
    folder = cfg["folder"] or "INBOX"
    mark_seen = bool(cfg["mark_seen"])

    if not username or not password:
        raise HTTPException(status_code=400, detail="Faltan usuario o clave IMAP (cargalos en /mail).")

    imap = None
    try:
        imap = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)

        typ, _ = imap.login(username, password)
        if typ != "OK":
            return ScanResult(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False,
                              message="Login IMAP falló")

        typ, _ = imap.select(folder, readonly=not mark_seen)
        if typ != "OK":
            return ScanResult(ok=False, login=True, folder=folder, unread=0, total=0, marked_seen=False,
                              message=f"No se pudo seleccionar la carpeta {folder}")

        typ, data = imap.search(None, "ALL")
        total = len((data[0] or b"").split()) if typ == "OK" else 0

        typ, data = imap.search(None, "UNSEEN")
        unseen_ids = (data[0] or b"").split() if typ == "OK" else []
        unread = len(unseen_ids)

        marked = False
        if mark_seen and unseen_ids:
            for msg_id in unseen_ids[:10]:
                imap.store(msg_id, "+FLAGS", "\\Seen")
            marked = True

        imap.close()
        imap.logout()
        return ScanResult(ok=True, login=True, folder=folder, unread=unread, total=total,
                          marked_seen=marked, message=None)
    except imaplib.IMAP4.error as e:
        try:
            if imap is not None:
                imap.logout()
        except Exception:
            pass
        return ScanResult(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False,
                          message=f"IMAP error: {e}")
    except Exception as e:
        try:
            if imap is not None:
                imap.logout()
        except Exception:
            pass
        return ScanResult(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False,
                          message=f"Error: {e}")
