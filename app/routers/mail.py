# app/routers/mail.py
import os, json, socket, imaplib, email
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from email.header import decode_header

TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/mail", tags=["mail"])

DATA_DIR = Path(os.getenv("DATA_DIR", "/var/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LINK_FILE = DATA_DIR / "mail_link.json"

def _env_bool(v: Optional[str], default=False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}

def _defaults_from_env() -> Dict[str, Any]:
    return dict(
        host=os.getenv("MAIL_HOST", "imap.gmail.com"),
        port=int(os.getenv("MAIL_PORT", "993") or 993),
        use_ssl=_env_bool(os.getenv("MAIL_USE_SSL", "true"), True),
        username=os.getenv("MAIL_USERNAME", ""),
        folder=os.getenv("MAIL_FOLDER", "INBOX") or "INBOX",
        mark_seen=_env_bool(os.getenv("MAIL_MARK_SEEN", "false"), False),
    )

def _load_linked() -> Dict[str, Any]:
    if LINK_FILE.exists():
        try:
            return json.loads(LINK_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_linked(data: dict) -> None:
    LINK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

class MailItem(BaseModel):
    uid: str
    from_email: Optional[str] = None
    subject: Optional[str] = None
    snippet: Optional[str] = None
    date: Optional[str] = None
    flags: Optional[List[str]] = None
    suspicious: bool = False
    score: float = 0.0
    reason: Optional[str] = None
    link: Optional[str] = None

class ScanResult(BaseModel):
    ok: bool
    login: bool
    folder: str
    unread: int
    total: int
    marked_seen: bool
    message: Optional[str] = None
    items: List[MailItem] = []

def _decode_hdr(v):
    if not v:
        return ""
    if isinstance(v, bytes):
        try:
            v = v.decode("utf-8", "ignore")
        except Exception:
            v = v.decode("latin-1", "ignore")
    parts = decode_header(v)
    out = []
    for txt, enc in parts:
        if isinstance(txt, bytes):
            try:
                out.append(txt.decode(enc or "utf-8", "ignore"))
            except Exception:
                out.append(txt.decode("latin-1", "ignore"))
        else:
            out.append(txt)
    return "".join(out).strip()

def _score_suspicious(subj: str, snip: str):
    text = f"{subj} {snip}".lower()
    kws = ["verify", "verificar", "password", "contraseña", "urgent", "urgente",
           "invoice", "factura", "payment", "pago", "bank", "banco", "reset"]
    hits = [k for k in kws if k in text]
    score = min(1.0, len(hits) * 0.2)
    return score, ", ".join(hits)

def _fetch_items(imap, folder, limit=50):
    typ, data = imap.uid("search", None, "ALL")
    uids = (data[0] or b"").split() if typ == "OK" else []
    uids = uids[-limit:]
    items = []
    for uid in reversed(uids):
        try:
            typ, data = imap.uid(
                "fetch", uid,
                b"(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODY.PEEK[TEXT]<0.512>)"
            )
            if typ != "OK" or not data:
                continue
            hdr_raw = b""
            snippet_raw = b""
            for part in data:
                if not isinstance(part, tuple):
                    continue
                block = part[1] or b""
                if b"HEADER.FIELDS" in part[0]:
                    hdr_raw += block
                elif b"TEXT" in part[0]:
                    snippet_raw += block
            msg = email.message_from_bytes(hdr_raw or b"")
            from_email = _decode_hdr(msg.get("From"))
            subject = _decode_hdr(msg.get("Subject"))
            date = _decode_hdr(msg.get("Date"))
            snippet = (snippet_raw or b"").decode("utf-8", "ignore")[:250]
            score, reason = _score_suspicious(subject, snippet)
            items.append(MailItem(
                uid=uid.decode(),
                from_email=from_email,
                subject=subject,
                date=date,
                snippet=snippet,
                suspicious=score >= 0.5,
                score=score,
                reason=reason,
                link=f"/mail/scanner?id={uid.decode()}",
            ))
        except Exception:
            continue
    return items

def _scan_impl() -> ScanResult:
    host = os.getenv("MAIL_HOST", "imap.gmail.com")
    port = int(os.getenv("MAIL_PORT", "993") or 993)
    use_ssl = _env_bool(os.getenv("MAIL_USE_SSL", "true"), True)
    username = os.getenv("MAIL_USERNAME", "")
    password = os.getenv("MAIL_PASSWORD", "")
    folder = os.getenv("MAIL_FOLDER", "INBOX") or "INBOX"
    mark_seen = _env_bool(os.getenv("MAIL_MARK_SEEN", "false"), False)

    if not username or not password:
        raise HTTPException(status_code=400, detail="Faltan MAIL_USERNAME o MAIL_PASSWORD")

    try:
        imap = imaplib.IMAP4_SSL(host, port, timeout=30) if use_ssl else imaplib.IMAP4(host, port, timeout=30)
        typ, _ = imap.login(username, password)
        if typ != "OK":
            return ScanResult(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False, message="Login IMAP falló", items=[])
        typ, _ = imap.select(folder, readonly=not mark_seen)
        if typ != "OK":
            return ScanResult(ok=False, login=True, folder=folder, unread=0, total=0, marked_seen=False, message=f"No se pudo abrir {folder}", items=[])
        typ, data = imap.search(None, "ALL")
        total = len((data[0] or b"").split()) if typ == "OK" else 0
        typ, data = imap.search(None, "UNSEEN")
        unseen_ids = (data[0] or b"").split() if typ == "OK" else []
        unread = len(unseen_ids)
        items = _fetch_items(imap, folder)
        try:
            imap.close(); imap.logout()
        except Exception:
            pass
        return ScanResult(ok=True, login=True, folder=folder, unread=unread, total=total, marked_seen=False, message=None, items=items)
    except (imaplib.IMAP4.error, socket.timeout) as e:
        return ScanResult(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False, message=str(e), items=[])
    except Exception as e:
        return ScanResult(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False, message=f"Error: {e}", items=[])

# === auth por cookie (mismo que usa main.py) ===
from app.security import get_current_user_cookie

@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_current_user_cookie)):
    linked = _load_linked().get(str(user["sub"]))
    ctx = {"request": request, "page_title": "Casillas de correo",
           "current_user": user, "defaults": _defaults_from_env(), "linked": linked}
    try:
        return templates.TemplateResponse("mail.html", ctx)
    except Exception:
        html = f"""<!doctype html><meta charset='utf-8'>
        <div style="font-family:system-ui;padding:24px">
          <h1>Mail</h1>
          <p>Cuenta guardada: <b>{(linked or {}).get("address","-")}</b></p>
          <form method="post" action="/mail/settings" style="display:flex;gap:8px;margin-top:12px">
            <input type="email" name="address" placeholder="tu@correo.com" required>
            <button>Guardar</button>
          </form>
          <p style="margin-top:12px"><a href="/mail/scanner">Ir al scanner</a></p>
        </div>"""
        return HTMLResponse(html)

# ---------- FIX 422: acepta form, json o query ----------
@router.get("/settings", include_in_schema=False)
def mail_settings_get():
    # Evita 422 cuando se accede por GET manualmente.
    return RedirectResponse(url="/mail/", status_code=303)

@router.post("/settings")
async def mail_settings(request: Request, user=Depends(get_current_user_cookie)):
    addr = None
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        try:
            data = await request.json()
            addr = (data or {}).get("address")
        except Exception:
            addr = None
    else:
        try:
            form = await request.form()
            addr = form.get("address")
        except Exception:
            addr = None
        # fallback por si alguien manda ?address=
        addr = addr or request.query_params.get("address")

    addr = (addr or "").strip().lower()
    if not addr or "@" not in addr:
        raise HTTPException(status_code=400, detail="Dirección inválida")

    data = _load_linked()
    data[str(user["sub"])] = {"address": addr}
    _save_linked(data)
    return RedirectResponse(url="/mail/", status_code=303)

@router.post("/connect")
async def mail_connect(request: Request, user=Depends(get_current_user_cookie)):
    # Alias que hace lo mismo que /settings
    return await mail_settings(request, user)

@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_current_user_cookie)):
    ctx = {"request": request, "page_title": "Mail Scanner",
           "current_user": user, "defaults": _defaults_from_env(),
           "linked": _load_linked().get(str(user["sub"]))}
    try:
        return templates.TemplateResponse("mail_scanner.html", ctx)
    except Exception:
        return HTMLResponse("<h1>Mail Scanner</h1>")

@router.get("/scan", response_model=ScanResult)
@router.post("/scan", response_model=ScanResult)
def mail_scan(user=Depends(get_current_user_cookie)):
    return _scan_impl()

# ---------- scheduler que invoca main.py ----------
def start_mail_scheduler(app):
    try:
        if not _env_bool(os.getenv("SCHEDULER_ENABLED", "0"), False):
            return
        import threading, time
        interval = int(os.getenv("SCHEDULER_INTERVAL_SEC", "600") or 600)

        def _job():
            uid = os.getenv("DYNO") or os.getenv("RENDER_INSTANCE_ID") or "local"
            while True:
                try:
                    res = _scan_impl()
                    print(f"[mail][sched] uid={uid} unread={res.unread} total={res.total} folder={res.folder}")
                except Exception as e:
                    print("[mail][sched] error:", repr(e))
                time.sleep(interval)

        threading.Thread(target=_job, daemon=True).start()
    except Exception as e:
        print("[mail][sched] start error:", repr(e))
