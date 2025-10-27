from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import get_current_user_cookie
from app.models import User

import imaplib, email, re, time, json, os
from typing import Generator

router = APIRouter(prefix="/mail", tags=["mail"])

# ========================
#  Pop-ups (SSE) en memoria
# ========================
USER_EVENTS: dict[int, list[dict]] = {}
def _emit_event(user_id: int, payload: dict):
    USER_EVENTS.setdefault(user_id, []).append(payload)

# Heurísticas simples de sospecha
SUSPICIOUS_PATTERNS = [
    re.compile(r"verify\\s+your\\s+account", re.I),
    re.compile(r"password\\s+expired", re.I),
    re.compile(r"urgent\\s+action", re.I),
    re.compile(r"click\\s+here", re.I),
    re.compile(r"factura|invoice|payment", re.I),
    re.compile(r"paypal|mercado\\s*pago|stripe|crypto", re.I),
]

def _imap_connect(server: str, port: int, use_ssl: bool, username: str, password: str):
    try:
        M = imaplib.IMAP4_SSL(server, port) if use_ssl else imaplib.IMAP4(server, port)
        M.login(username, password)
        M.select("INBOX")
        return M
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error IMAP: {e}")

def _is_suspicious(msg: email.message.Message) -> bool:
    subject = msg.get("Subject", "")
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body += part.get_payload(decode=True).decode(errors="ignore")
                except:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(errors="ignore")
        except:
            body = str(msg.get_payload())
    return any(p.search(subject) or p.search(body) for p in SUSPICIOUS_PATTERNS)

# =====================================================
#  TUS RUTAS ORIGINALES (se mantienen idénticas)
# =====================================================

@router.get("/", response_class=HTMLResponse, response_model=None)
def mail_index(request: Request, db: Session = Depends(get_db)):
    # payload desde cookie + lookup del usuario real
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
    <p><a href="/dashboard">Volver</a></p>
    """
    return HTMLResponse(html)

@router.post("/add", response_model=None)
def add_mail_account(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    # Lógica simplificada, deberías guardar la cuenta en la DB
    print(f"[mail] user={user.email} agregó cuenta {email}")
    return HTMLResponse(f"<p>Cuenta {email} agregada.</p><p><a href='/mail'>Volver</a></p>")

# ==========================================
#  NUEVAS RUTAS (vincular, escanear, SSE)
# ==========================================

@router.get("/connect", response_class=HTMLResponse)
def connect_form(request: Request, user=Depends(get_current_user_cookie)):
    return request.app.state.templates.TemplateResponse(
        "mail_connect.html",
        {"request": request, "ok": False}
    )

@router.post("/connect", response_class=HTMLResponse)
def connect_imap(
    request: Request,
    email_addr: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    imap_server: str = Form(...),
    imap_port: int = Form(...),
    use_ssl: bool = Form(False),
    user=Depends(get_current_user_cookie),
):
    # Para demo: guardamos en variables de entorno (en producción -> DB cifrada)
    os.environ["IMAP_EMAIL"] = email_addr
    os.environ["IMAP_USER"]  = username
    os.environ["IMAP_PASS"]  = password
    os.environ["IMAP_SERVER"] = imap_server
    os.environ["IMAP_PORT"]   = str(imap_port)
    os.environ["IMAP_SSL"]    = "1" if use_ssl else "0"

    ctx = {"request": request, "ok": True, "email_addr": email_addr}
    return request.app.state.templates.TemplateResponse("mail_connect.html", ctx)

@router.get("/scanner", response_class=HTMLResponse)
def scanner_page(request: Request, user=Depends(get_current_user_cookie)):
    html = """
    <h1>Mail Scanner</h1>
    <button onclick="scan()">Escanear últimos correos</button>
    <ul id='out'></ul>
    <script>
    async function scan(){
      const r = await fetch('/mail/scan', {method:'POST'});
      const d = await r.json();
      document.getElementById('out').innerHTML =
        (d.findings||[]).map(f=>`<li>${f.subject} - ${f.from}</li>`).join('');
    }
    </script>
    <script>
    if ('Notification' in window) Notification.requestPermission();
    const es = new EventSource('/mail/stream');
    es.addEventListener('mail_alert', e=>{
      const data = JSON.parse(e.data);
      try{ new Notification('Correo sospechoso', { body: `${data.subject} · ${data.from}` }); }
      catch(err){ console.log('Notif:', err); }
    });
    </script>
    <p><a href='/dashboard'>Volver</a></p>
    """
    return HTMLResponse(html)

@router.post("/scan")
def scan_now(user=Depends(get_current_user_cookie)):
    email_addr = os.getenv("IMAP_EMAIL")
    username   = os.getenv("IMAP_USER") or email_addr
    password   = os.getenv("IMAP_PASS")
    server     = os.getenv("IMAP_SERVER", "imap.gmail.com")
    port       = int(os.getenv("IMAP_PORT", "993"))
    use_ssl    = os.getenv("IMAP_SSL", "1") == "1"

    if not email_addr or not password:
        raise HTTPException(400, "No hay cuenta IMAP vinculada.")

    M = _imap_connect(server, port, use_ssl, username, password)
    findings = []
    try:
        typ, data = M.search(None, "ALL")
        ids = data[0].split()[-20:]
        for eid in reversed(ids):
            typ, msg_data = M.fetch(eid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            if _is_suspicious(msg):
                finding = {"subject": msg.get("Subject", "(sin asunto)"), "from": msg.get("From", "")}
                findings.append(finding)
                _emit_event(user.id, {"type": "mail_alert", "data": finding})
        return {"ok": True, "findings": findings}
    finally:
        try: M.logout()
        except: pass

@router.get("/stream")
def stream_alerts(user=Depends(get_current_user_cookie)):
    def gen() -> Generator[bytes, None, None]:
        yield b"event: init\\ndata: {\"ok\":true}\\n\\n"
        while True:
            bucket = USER_EVENTS.get(user.id, [])
            while bucket:
                ev = bucket.pop(0)
                yield f"event: {ev['type']}\\ndata: {json.dumps(ev['data'])}\\n\\n".encode()
            time.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream")
