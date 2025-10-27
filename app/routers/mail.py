# app/routers/mail.py
from __future__ import annotations
import os, imaplib, email, re, time, json
from typing import Generator

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import get_current_user_cookie
from app.models import User

router = APIRouter(prefix="/mail", tags=["mail"])

# -----------------------
# Utilidades y estado
# -----------------------
_PATTERNS = [
    re.compile(r"verify\s+your\s+account", re.I),
    re.compile(r"password\s+expired", re.I),
    re.compile(r"urgent\s+action", re.I),
    re.compile(r"click\s+here", re.I),
    re.compile(r"factura|invoice|payment", re.I),
    re.compile(r"paypal|mercado\s*pago|stripe|crypto", re.I),
]
_USER_EVENTS: dict[int, list[dict]] = {}


def _emit(uid: int, payload: dict) -> None:
    _USER_EVENTS.setdefault(uid, []).append(payload)


def _imap_login() -> imaplib.IMAP4:
    host = os.getenv("MAIL_HOST", "imap.gmail.com")
    port = int(os.getenv("MAIL_PORT", "993"))
    use_ssl = str(os.getenv("MAIL_USE_SSL", "true")).lower() in {"1", "true", "yes", "on"}
    user = os.getenv("MAIL_USERNAME") or os.getenv("MAIL_USER") or ""
    pwd = os.getenv("MAIL_PASSWORD") or os.getenv("MAIL_PASS") or ""

    if not user or not pwd:
        raise HTTPException(400, "Faltan credenciales IMAP (MAIL_USERNAME / MAIL_PASSWORD).")

    M = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
    M.login(user, pwd)
    folder = os.getenv("MAIL_FOLDER", "INBOX")
    M.select(folder)
    return M


def _is_suspicious(msg: email.message.Message) -> bool:
    subj = msg.get("Subject", "") or ""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body += part.get_payload(decode=True).decode(errors="ignore")
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(errors="ignore")
        except Exception:
            body = str(msg.get_payload())
    return any(p.search(subj) or p.search(body) for p in _PATTERNS)


# -----------------------
# Vistas
# -----------------------
@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, db: Session = Depends(get_db)):
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    html = f"""
    <h1>Casillas de correo</h1>
    <p>Bienvenido, {user.email}</p>

    <form method="post" action="/mail/add">
      <label>Dirección: <input name="email" type="email" required></label>
      <button type="submit">Agregar</button>
    </form>

    <p><a href="/mail/connect">Vincular casilla (IMAP)</a></p>
    <p><a href="/mail/scanner">Mail Scanner</a></p>
    <p><a href="/dashboard">Volver</a></p>
    """
    return HTMLResponse(html)


@router.post("/add")
def add_mail_account(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    print(f"[mail] user={user.email} agregó cuenta {email}")
    return HTMLResponse(f"<p>Cuenta {email} agregada.</p><p><a href='/mail'>Volver</a></p>")


@router.get("/connect", response_class=HTMLResponse)
def connect_get(request: Request, user=Depends(get_current_user_cookie)):
    return request.app.state.templates.TemplateResponse("mail_connect.html", {"request": request, "ok": False})


@router.post("/connect", response_class=HTMLResponse)
def connect_post(
    request: Request,
    email_addr: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    imap_server: str = Form("imap.gmail.com"),
    imap_port: int = Form(993),
    use_ssl: bool = Form(True),
    user=Depends(get_current_user_cookie),
):
    # Persistimos en env (en Render podés setearlos definitivos en “Environment”)
    os.environ["MAIL_HOST"] = imap_server
    os.environ["MAIL_PORT"] = str(imap_port)
    os.environ["MAIL_USE_SSL"] = "1" if use_ssl else "0"
    os.environ["MAIL_USERNAME"] = username or email_addr
    os.environ["MAIL_PASSWORD"] = password
    os.environ["MAIL_FOLDER"] = os.getenv("MAIL_FOLDER", "INBOX")
    return request.app.state.templates.TemplateResponse(
        "mail_connect.html",
        {"request": request, "ok": True, "email_addr": email_addr},
    )


@router.get("/scanner", response_class=HTMLResponse)
def scanner(request: Request, user=Depends(get_current_user_cookie)):
    html = """
    <h1>Mail Scanner</h1>
    <button onclick="scan()">Escanear últimos correos</button>
    <ul id='out' style="font-family:system-ui"></ul>
    <script>
      async function scan(){
        const r = await fetch('/mail/scan', {method:'POST'});
        const d = await r.json();
        document.getElementById('out').innerHTML =
          (d.findings||[]).map(f=>`<li><b>${f.subject}</b> — ${f.from}</li>`).join('') || '<li>Sin sospechosos</li>';
      }
      if ('Notification' in window) { Notification.requestPermission(); }
      const es = new EventSource('/mail/stream');
      es.addEventListener('mail_alert', e=>{
        const d = JSON.parse(e.data);
        try { new Notification('Correo sospechoso', { body: `${d.subject} · ${d.from}` }); } catch(_){}
      });
    </script>
    <p><a href='/mail'>Volver</a></p>
    """
    return HTMLResponse(html)


@router.post("/scan")
def scan(user=Depends(get_current_user_cookie)):
    M = _imap_login()
    findings = []
    try:
        typ, data = M.search(None, "ALL")
        ids = (data[0] or b"").split()[-50:]  # últimos 50
        for eid in reversed(ids):
            typ, msg_data = M.fetch(eid, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            if _is_suspicious(msg):
                f = {"subject": msg.get("Subject", "(sin asunto)"), "from": msg.get("From", "")}
                findings.append(f)
                _emit(int(user["sub"]), {"type": "mail_alert", "data": f})
        return {"ok": True, "findings": findings}
    finally:
        try: M.logout()
        except Exception: pass


@router.get("/stream")
def stream(user=Depends(get_current_user_cookie)):
    def gen() -> Generator[bytes, None, None]:
        yield b"event: init\ndata: {\"ok\":true}\n\n"
        uid = int(user["sub"])
        while True:
            q = _USER_EVENTS.get(uid, [])
            while q:
                ev = q.pop(0)
                yield f"event: {ev['type']}\ndata: {json.dumps(ev['data'])}\n\n".encode()
            time.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream")


# Fallback (por si el JS lo consulta)
@router.get("/alerts/unread_count")
def unread_count():
    return {"unread": 0, "count": 0}
