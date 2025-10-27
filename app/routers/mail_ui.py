# app/routers/mail_ui.py
import json, os
from pathlib import Path
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from app.security import get_current_user_cookie
from app.database import SessionLocal
from app.models import User

router = APIRouter()

CREDS_PATH = Path("/var/data/mail_creds.json")

def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _current_user(request: Request, db):
    payload = get_current_user_cookie(request)
    u = db.query(User).filter(User.id == payload["sub"]).first()
    if not u:
        raise HTTPException(status_code=401, detail="No autenticado")
    return u

def load_creds():
    if CREDS_PATH.exists():
        try:
            return json.loads(CREDS_PATH.read_text("utf-8"))
        except Exception:
            return {}
    return {}

def save_creds(data: dict):
    CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

@router.get("/mail/connect", include_in_schema=False)
def connect_get(request: Request, db=Depends(_get_db)):
    _ = _current_user(request, db)
    # valores por defecto desde env o json guardado
    saved = load_creds()
    ctx = {
        "request": request,
        "vals": {
            "host": saved.get("host", os.getenv("MAIL_HOST", "imap.gmail.com")),
            "port": saved.get("port", os.getenv("MAIL_PORT", "993")),
            "use_ssl": str(saved.get("use_ssl", str(os.getenv("MAIL_USE_SSL", "true")).lower() in ("1","true","yes"))).lower(),
            "username": saved.get("username", os.getenv("MAIL_USERNAME", "")),
            "folder": saved.get("folder", os.getenv("MAIL_FOLDER", "INBOX")),
        },
        "has_password": bool(saved.get("password")),
    }
    return request.app.state.templates.TemplateResponse("mail_link_imap.html", ctx)

@router.post("/mail/connect", include_in_schema=False)
def connect_post(
    request: Request,
    db=Depends(_get_db),
    host: str = Form(...),
    port: str = Form(...),
    use_ssl: str = Form("true"),
    username: str = Form(...),
    password: str = Form(""),
    folder: str = Form("INBOX"),
):
    _ = _current_user(request, db)
    # normalizar
    try:
        port_i = int(port)
    except Exception:
        port_i = 993
    use_ssl_b = str(use_ssl).lower() in ("1","true","yes","on")
    data = load_creds()
    data.update({
        "host": host.strip(),
        "port": port_i,
        "use_ssl": use_ssl_b,
        "username": username.strip(),
        # si viene vacío, conservamos el anterior (para no mostrarlo en claro)
        **({"password": password} if password else {}),
        "folder": (folder or "INBOX").strip() or "INBOX",
    })
    save_creds(data)
    return RedirectResponse("/mail/scanner?saved=1", status_code=status.HTTP_303_SEE_OTHER)
