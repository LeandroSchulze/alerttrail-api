from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
import os, json, imaplib, ssl
from pathlib import Path
from cryptography.fernet import Fernet

from app.security import get_current_user_cookie

router = APIRouter(prefix="/mail", tags=["mail"])

# === Config ===
DATA_DIR = Path(os.getenv("DATA_DIR", "/var/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LINK_FILE = DATA_DIR / "mail_link.json"

FERNET_KEY = os.getenv("MAIL_CRYPT_KEY")
fernet = Fernet(FERNET_KEY.encode()) if FERNET_KEY else None


# === Helpers ===
def _env_bool(v: str, default=False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}

def _load_linked():
    if LINK_FILE.exists():
        try:
            return json.loads(LINK_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_linked(data: dict):
    LINK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _defaults_from_env():
    """Valores por defecto (display)."""
    return dict(
        host=os.getenv("MAIL_HOST", "imap.gmail.com"),
        port=int(os.getenv("MAIL_PORT", "993") or 993),
        use_ssl=_env_bool(os.getenv("MAIL_USE_SSL", "true"), True),
        username=os.getenv("MAIL_USERNAME", ""),
        folder=os.getenv("MAIL_FOLDER", "INBOX") or "INBOX",
        mark_seen=_env_bool(os.getenv("MAIL_MARK_SEEN", "false"), False),
    )

# === UI principal ===
@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_current_user_cookie)):
    linked = _load_linked().get(str(user["sub"]))
    ctx = {
        "request": request,
        "page_title": "Casillas de correo",
        "current_user": user,
        "linked": linked,
        "defaults": _defaults_from_env(),
    }
    return request.app.state.templates.TemplateResponse("mail.html", ctx)


# === Conectar casilla (formulario) ===
@router.get("/connect", response_class=HTMLResponse)
def mail_connect_form(request: Request, user=Depends(get_current_user_cookie)):
    ctx = {
        "request": request,
        "page_title": "Vincular casilla (IMAP)",
        "current_user": user,
        "defaults": _defaults_from_env(),
    }
    return request.app.state.templates.TemplateResponse("mail_connect.html", ctx)


@router.post("/connect")
def mail_connect_post(
    request: Request,
    email_addr: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    imap_server: str = Form("imap.gmail.com"),
    imap_port: int = Form(993),
    use_ssl: bool = Form(True),
    db_user=Depends(get_current_user_cookie),
):
    email_addr = (email_addr or "").strip().lower()
    if not email_addr or "@" not in email_addr:
        raise HTTPException(status_code=400, detail="Email inválido")

    user_id = str(db_user["sub"])
    data = _load_linked()
    enc_pass = fernet.encrypt(password.encode()).decode() if fernet else password

    data[user_id] = {
        "email": email_addr,
        "username": username,
        "imap_server": imap_server,
        "imap_port": imap_port,
        "use_ssl": use_ssl,
        "password": enc_pass,
    }
    _save_linked(data)

    return RedirectResponse(url="/mail?ok=1", status_code=303)


# === Mail Scanner ===
class ScanResult(BaseModel):
    ok: bool
    login: bool
    folder: str
    unread: int
    total: int
    marked_seen: bool
    message: str | None = None


@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_current_user_cookie)):
    ctx = {
        "request": request,
        "page_title": "Mail Scanner",
        "current_user": user,
        "linked": _load_linked().get(str(user["sub"])),
        "defaults": _defaults_from_env(),
    }
    return request.app.state.templates.TemplateResponse("mail_scanner.html", ctx)


@router.post("/scan", response_model=ScanResult)
def mail_scan(user=Depends(get_current_user_cookie)):
    # Primero intenta usar datos vinculados por usuario
    user_id = str(user["sub"])
    linked = _load_linked().get(user_id)

    if linked:
        host = linked.get("imap_server", "imap.gmail.com")
        port = int(linked.get("imap_port", 993))
        use_ssl = bool(linked.get("use_ssl", True))
        username = linked.get("username")
        password = linked.get("password")
        if fernet:
            try:
                password = fernet.decrypt(password.encode()).decode()
            except Exception:
                pass
    else:
        # fallback a variables de entorno
        host = os.getenv("MAIL_HOST", "imap.gmail.com")
        port = int(os.getenv("MAIL_PORT", "993") or 993)
        use_ssl = _env_bool(os.getenv("MAIL_USE_SSL", "true"), True)
        username = os.getenv("MAIL_USERNAME", "")
        password = os.getenv("MAIL_PASSWORD", "")

    folder = os.getenv("MAIL_FOLDER", "INBOX") or "INBOX"
    mark_seen = _env_bool(os.getenv("MAIL_MARK_SEEN", "false"), False)

    if not username or not password:
        raise HTTPException(status_code=400, detail="Faltan credenciales IMAP")

    imap = None
    try:
        imap = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
        typ, _ = imap.login(username, password)
        if typ != "OK":
            return ScanResult(ok=False, login=False, folder=folder, unread=0, total=0,
                              marked_seen=False, message="Login IMAP falló")

        typ, _ = imap.select(folder, readonly=not mark_seen)
        if typ != "OK":
            return ScanResult(ok=False, login=True, folder=folder, unread=0, total=0,
                              marked_seen=False, message=f"No se pudo abrir {folder}")

        typ, data = imap.search(None, "ALL")
        total = len((data[0] or b"").split()) if typ == "OK" else 0

        typ, data = imap.search(None, "UNSEEN")
        unseen = (data[0] or b"").split() if typ == "OK" else []
        unread = len(unseen)

        if mark_seen and unseen:
            for msg_id in unseen[:10]:
                imap.store(msg_id, "+FLAGS", "\\Seen")

        imap.close()
        imap.logout()

        return ScanResult(ok=True, login=True, folder=folder,
                          unread=unread, total=total, marked_seen=mark_seen, message=None)
    except imaplib.IMAP4.error as e:
        if imap:
            try:
                imap.logout()
            except Exception:
                pass
        return ScanResult(ok=False, login=False, folder=folder,
                          unread=0, total=0, marked_seen=False, message=f"IMAP error: {e}")
    except Exception as e:
        if imap:
            try:
                imap.logout()
            except Exception:
                pass
        return ScanResult(ok=False, login=False, folder=folder,
                          unread=0, total=0, marked_seen=False, message=f"Error: {e}")
