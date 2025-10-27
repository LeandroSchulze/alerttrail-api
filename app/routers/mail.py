from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
import os, json, imaplib, ssl
from pathlib import Path

from app.security import get_current_user_cookie

router = APIRouter(prefix="/mail", tags=["mail"])

# Archivo plano para guardar el mail “linkeado” por usuario (simple y suficiente)
DATA_DIR = Path(os.getenv("DATA_DIR", "/var/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LINK_FILE = DATA_DIR / "mail_link.json"

def _env_bool(v: str, default=False) -> bool:
    if v is None: return default
    return str(v).strip().lower() in {"1","true","yes","y","on"}

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
    """Valores que usa el scanner; se muestran como ayuda en el UI."""
    return dict(
        host=os.getenv("MAIL_HOST", "imap.gmail.com"),
        port=int(os.getenv("MAIL_PORT", "993") or 993),
        use_ssl=_env_bool(os.getenv("MAIL_USE_SSL", "true"), True),
        username=os.getenv("MAIL_USERNAME", ""),
        folder=os.getenv("MAIL_FOLDER", "INBOX") or "INBOX",
        mark_seen=_env_bool(os.getenv("MAIL_MARK_SEEN", "false"), False),
    )

@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_current_user_cookie)):
    # Estado
    linked = _load_linked().get(str(user["sub"]))  # por usuario
    ctx = {
        "request": request,
        "page_title": "Casillas de correo",
        "current_user": user,
        "linked": linked,                # None o dict con {"address": "..."}
        "defaults": _defaults_from_env() # host/port/ssl/etc (solo display)
    }
    return request.app.state.templates.TemplateResponse("mail.html", ctx)

@router.post("/connect")
def mail_connect(address: str = Form(...), user=Depends(get_current_user_cookie)):
    address = (address or "").strip().lower()
    if not address or "@" not in address:
        raise HTTPException(status_code=400, detail="Dirección inválida")

    data = _load_linked()
    data[str(user["sub"])] = {"address": address}
    _save_linked(data)

    return RedirectResponse(url="/mail", status_code=303)

# ---- Scanner UI ----
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
    # Usa las ENV para conectar
    host   = os.getenv("MAIL_HOST", "imap.gmail.com")
    port   = int(os.getenv("MAIL_PORT", "993") or 993)
    use_ssl = _env_bool(os.getenv("MAIL_USE_SSL", "true"), True)
    username = os.getenv("MAIL_USERNAME", "")
    password = os.getenv("MAIL_PASSWORD", "")
    folder   = os.getenv("MAIL_FOLDER", "INBOX") or "INBOX"
    mark_seen = _env_bool(os.getenv("MAIL_MARK_SEEN", "false"), False)

    if not username or not password:
        raise HTTPException(status_code=400, detail="Faltan MAIL_USERNAME o MAIL_PASSWORD en variables de entorno")

    imap = None
    try:
        if use_ssl:
            imap = imaplib.IMAP4_SSL(host, port)
        else:
            imap = imaplib.IMAP4(host, port)

        typ, _ = imap.login(username, password)
        if typ != "OK":
            return ScanResult(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False,
                              message="Login IMAP falló")

        typ, _ = imap.select(folder, readonly=not mark_seen)
        if typ != "OK":
            return ScanResult(ok=False, login=True, folder=folder, unread=0, total=0, marked_seen=False,
                              message=f"No se pudo seleccionar la carpeta {folder}")

        # total
        typ, data = imap.search(None, "ALL")
        total = len((data[0] or b"").split()) if typ == "OK" else 0

        # unread
        typ, data = imap.search(None, "UNSEEN")
        unseen_ids = (data[0] or b"").split() if typ == "OK" else []
        unread = len(unseen_ids)

        marked = False
        if mark_seen and unseen_ids:
            # marcar como visto los primeros N para prueba (máx 10 para no arrasar)
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
