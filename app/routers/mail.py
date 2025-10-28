from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
import os, json, imaplib, time
from pathlib import Path
from threading import Event, Thread

from app.security import get_current_user_cookie

router = APIRouter(prefix="/mail", tags=["mail"])

# ------------ Storage plano por usuario ------------
DATA_DIR = Path(os.getenv("DATA_DIR", "/var/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LINK_FILE = DATA_DIR / "mail_link.json"

def _env_bool(v: str | None, default=False) -> bool:
    if v is None: return default
    return str(v).strip().lower() in {"1","true","yes","y","on"}

def _load_all() -> dict:
    if LINK_FILE.exists():
        try:
            return json.loads(LINK_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_all(data: dict):
    LINK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ------------ Cifrado opcional de password ------------
_FERNET = None
try:
    from cryptography.fernet import Fernet
    key = os.getenv("FERNET_SECRET")
    if key:
        if len(key) != 44:  # si viene sin base64 urlsafe, permito raw y lo normalizo
            try:
                # aceptar hex/bytes y derivar a 32 bytes base64 urlsafe
                import base64, hashlib
                key = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()).decode()
            except Exception:
                pass
        _FERNET = Fernet(key)
except Exception:
    _FERNET = None

def _enc(pw: str | None) -> str | None:
    if not pw: return None
    if not _FERNET: return pw  # fallback sin cifrar (recomendado configurar FERNET_SECRET)
    return _FERNET.encrypt(pw.encode()).decode()

def _dec(pw_enc: str | None) -> str | None:
    if not pw_enc: return None
    if not _FERNET: return pw_enc
    try:
        return _FERNET.decrypt(pw_enc.encode()).decode()
    except Exception:
        return None

# ------------ Defaults para el UI / scanner por ENV ------------
def _defaults_from_env():
    return dict(
        host=os.getenv("MAIL_HOST", "imap.gmail.com"),
        port=int(os.getenv("MAIL_PORT", "993") or 993),
        use_ssl=_env_bool(os.getenv("MAIL_USE_SSL", "true"), True),
        username=os.getenv("MAIL_USERNAME", ""),
        folder=os.getenv("MAIL_FOLDER", "INBOX") or "INBOX",
        mark_seen=_env_bool(os.getenv("MAIL_MARK_SEEN", "false"), False),
    )

def _user_key(user) -> str:
    return str(user["sub"])

def _get_user_cfg(user):
    data = _load_all()
    cur = data.get(_user_key(user))
    # normalizar estructura
    if cur and "imap_cfg" not in cur:
        cur["imap_cfg"] = {}
    return cur

def _set_user_cfg(user, obj):
    data = _load_all()
    data[_user_key(user)] = obj
    _save_all(data)

# ------------ Vistas HTML ------------
@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_current_user_cookie)):
    linked = _get_user_cfg(user)
    ctx = {
        "request": request,
        "page_title": "Casillas de correo",
        "current_user": user,
        "linked": linked,
        "defaults": _defaults_from_env()
    }
    return request.app.state.templates.TemplateResponse("mail.html", ctx)

@router.post("/connect")
def mail_connect(address: str = Form(...), user=Depends(get_current_user_cookie)):
    address = (address or "").strip().lower()
    if not address or "@" not in address:
        raise HTTPException(status_code=400, detail="Dirección inválida")

    cur = _get_user_cfg(user) or {}
    cur["address"] = address
    cur.setdefault("imap_cfg", {})
    _set_user_cfg(user, cur)

    return RedirectResponse(url="/mail/", status_code=303)

@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_current_user_cookie)):
    ctx = {
        "request": request,
        "page_title": "Mail Scanner",
        "current_user": user,
        "linked": _get_user_cfg(user),
        "defaults": _defaults_from_env(),
    }
    return request.app.state.templates.TemplateResponse("mail_scanner.html", ctx)

# ------------ Guardado de IMAP settings ------------
@router.post("/settings")
def mail_settings(
    user=Depends(get_current_user_cookie),
    host: str = Form(...),
    port: int = Form(...),
    username: str = Form(""),
    password: str = Form(""),
    folder: str = Form("INBOX"),
    use_ssl: str = Form("on"),
    mark_seen: str = Form(""),
):
    cur = _get_user_cfg(user) or {}
    cur.setdefault("imap_cfg", {})

    cur["imap_cfg"] = {
        "host": (host or "").strip(),
        "port": int(port or 993),
        "username": (username or "").strip(),
        "password": _enc(password.strip()) if password else cur["imap_cfg"].get("password"),  # si no envían, se mantiene
        "folder": (folder or "INBOX").strip() or "INBOX",
        "use_ssl": _env_bool(use_ssl, True),
        "mark_seen": _env_bool(mark_seen, False),
    }
    _set_user_cfg(user, cur)
    return RedirectResponse(url="/mail/?saved=1", status_code=303)

# ------------ Scanner ------------
class ScanResult(BaseModel):
    ok: bool
    login: bool
    folder: str
    unread: int
    total: int
    marked_seen: bool
    message: str | None = None

def _scan_with_cfg(cfg) -> ScanResult:
    host   = cfg.get("host") or "imap.gmail.com"
    port   = int(cfg.get("port") or 993)
    use_ssl = bool(cfg.get("use_ssl", True))
    username = cfg.get("username") or os.getenv("MAIL_USERNAME", "")
    password = _dec(cfg.get("password")) or os.getenv("MAIL_PASSWORD", "")
    folder   = cfg.get("folder") or os.getenv("MAIL_FOLDER", "INBOX") or "INBOX"
    mark_seen = bool(cfg.get("mark_seen", False))

    if not username or not password:
        raise HTTPException(status_code=400, detail="Faltan usuario/contraseña IMAP")

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

        imap.close(); imap.logout()
        return ScanResult(ok=True, login=True, folder=folder, unread=unread, total=total, marked_seen=marked)
    except imaplib.IMAP4.error as e:
        try:
            if imap is not None: imap.logout()
        except Exception: pass
        return ScanResult(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False,
                          message=f"IMAP error: {e}")
    except Exception as e:
        try:
            if imap is not None: imap.logout()
        except Exception: pass
        return ScanResult(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False,
                          message=f"Error: {e}")

@router.post("/scan", response_model=ScanResult)
def mail_scan(user=Depends(get_current_user_cookie)):
    cfg = (_get_user_cfg(user) or {}).get("imap_cfg") or _defaults_from_env()
    # si defaults vienen de ENV y no hay pass cifrada, se usa MAIL_PASSWORD
    return _scan_with_cfg(cfg)

# ------------ Scheduler (cada 60s si SCHEDULER_ENABLED=1) ------------
_stop = Event()
_thread = None

def _all_users_items():
    data = _load_all()
    for uid, obj in data.items():
        cfg = (obj or {}).get("imap_cfg")
        if cfg: yield uid, cfg

def _scheduler_loop(app):
    interval = int(os.getenv("SCHEDULER_INTERVAL_SEC", "60") or 60)
    while not _stop.is_set():
        try:
            for uid, cfg in _all_users_items():
                res = _scan_with_cfg(cfg)
                # lugar para levantar alertas reales; por ahora logueamos
                if res.ok and res.unread > 0:
                    print(f"[mail][sched] uid={uid} unread={res.unread} total={res.total} folder={res.folder}")
        except Exception as e:
            print("[mail][sched] error:", repr(e))
        _stop.wait(interval)

def start_mail_scheduler(app):
    global _thread
    if not _env_bool(os.getenv("SCHEDULER_ENABLED"), False):
        return
    if _thread and _thread.is_alive():  # ya está corriendo
        return
    print("[mail][sched] starting background scanner (60s)...")
    _thread = Thread(target=_scheduler_loop, args=(app,), daemon=True)
    _thread.start()

def stop_mail_scheduler():
    _stop.set()
