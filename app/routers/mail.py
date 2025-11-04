from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from jinja2 import TemplateNotFound
from pathlib import Path
import os, json, imaplib, socket
from typing import Optional, List, Dict, Any

from app.security import get_current_user_cookie
from app.main import app  # para reusar templates montados en main
from app.services.mail_scan import scan_inbox  # <-- usa tu implementación existente

router = APIRouter(prefix="/mail", tags=["mail"])

# ===== Helpers ENV/FS =====
DATA_DIR = Path(os.getenv("DATA_DIR", "/var/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LINK_FILE = DATA_DIR / "mail_link.json"

def _env_bool(v: Optional[str], default=False) -> bool:
    if v is None: return default
    return str(v).strip().lower() in {"1","true","yes","y","on"}

def _defaults_from_env() -> Dict[str, Any]:
    return dict(
        host=os.getenv("MAIL_HOST", "imap.gmail.com"),
        port=int(os.getenv("MAIL_PORT", "993") or 993),
        use_ssl=_env_bool(os.getenv("MAIL_USE_SSL", "true"), True),
        username=os.getenv("MAIL_USERNAME", ""),
        folder=os.getenv("MAIL_FOLDER", "INBOX") or "INBOX",
        mark_seen=_env_bool(os.getenv("MAIL_MARK_SEEN", "false"), False),
        max_msgs=int(os.getenv("MAIL_MAX_MSGS", "20") or 20),
    )

# ===== Views =====
@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_current_user_cookie)):
    ctx = {"request": request, "page_title": "Casillas de correo",
           "current_user": user, "defaults": _defaults_from_env()}
    try:
        return app.state.templates.TemplateResponse("mail.html", ctx)
    except TemplateNotFound:
        html = """<!doctype html><meta charset='utf-8'>
        <div style="font-family:system-ui;padding:24px">
          <h1>Mail</h1>
          <p><a href="/mail/scanner">Ir al scanner</a></p>
        </div>"""
        return HTMLResponse(html)

@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_current_user_cookie)):
    ctx = {"request": request, "page_title": "Mail Scanner",
           "current_user": user, "defaults": _defaults_from_env()}
    try:
        return app.state.templates.TemplateResponse("mail_scanner.html", ctx)
    except TemplateNotFound:
        return HTMLResponse("<h1>Mail Scanner</h1>")

# ===== API =====
@router.get("/scan")
@router.post("/scan")
def mail_scan(user=Depends(get_current_user_cookie)):
    """Devuelve resumen + items analizados para que /mail/scanner pueda mostrar la tabla."""
    cfg = _defaults_from_env()
    host, port, use_ssl = cfg["host"], cfg["port"], cfg["use_ssl"]
    username = cfg["username"]
    password = os.getenv("MAIL_PASSWORD", "")
    folder   = cfg["folder"]
    max_msgs = cfg["max_msgs"]
    mark_seen = cfg["mark_seen"]

    if not username or not password:
        raise HTTPException(status_code=400, detail="Faltan MAIL_USERNAME o MAIL_PASSWORD")

    total = 0
    unread = 0
    # 1) Contar totales y no leídos (login rápido)
    try:
        imap = imaplib.IMAP4_SSL(host, port, timeout=30) if use_ssl else imaplib.IMAP4(host, port, timeout=30)
        typ, _ = imap.login(username, password)
        if typ != "OK":
            return {"ok": False, "login": False, "folder": folder, "unread": 0, "total": 0,
                    "marked_seen": False, "message": "Login IMAP falló"}
        typ, _ = imap.select(folder, readonly=not mark_seen)
        if typ != "OK":
            try:
                imap.logout()
            except Exception:
                pass
            return {"ok": False, "login": True, "folder": folder, "unread": 0, "total": 0,
                    "marked_seen": False, "message": f"No se pudo abrir {folder}"}

        typ, data = imap.search(None, "ALL")
        total = len((data[0] or b"").split()) if typ == "OK" else 0
        typ, data = imap.search(None, "UNSEEN")
        unread = len((data[0] or b"").split()) if typ == "OK" else 0
        try:
            imap.close(); imap.logout()
        except Exception:
            pass
    except (imaplib.IMAP4.error, socket.timeout) as e:
        return {"ok": False, "login": False, "folder": folder, "unread": 0, "total": 0,
                "marked_seen": False, "message": str(e)}

    # 2) Analizar mensajes (usa tu service existente)
    try:
        items = scan_inbox(host=host, username=username, password=password,
                           port=port, use_ssl=use_ssl, mailbox=folder, max_msgs=max_msgs)
    except Exception as e:
        # Si falla el análisis, devolvemos al menos el resumen
        return {"ok": True, "login": True, "folder": folder, "unread": unread, "total": total,
                "marked_seen": False, "message": f"Scan parcial: {e}", "items": []}

    return {"ok": True, "login": True, "folder": folder, "unread": unread, "total": total,
            "marked_seen": False, "message": None, "items": items}
