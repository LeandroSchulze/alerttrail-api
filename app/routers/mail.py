# app/routers/mail.py
import os
import imaplib
import email
from email.header import decode_header, make_header
from datetime import datetime, timedelta
from typing import List, Tuple

import asyncio
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db, SessionLocal
from app.security import get_current_user_cookie

# ====== helpers de cifrado ======
def _get_fernet():
    # import perezoso
    from cryptography.fernet import Fernet
    import base64, hashlib
    env_key = os.getenv("MAIL_CRYPT_KEY")
    if env_key:
        try:
            return Fernet(env_key.encode() if isinstance(env_key, str) else env_key)
        except Exception:
            pass
    seed = (os.getenv("JWT_SECRET", "change-me") + "_mail").encode()
    derived = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(derived)

# ====== guard de plan ======
def _is_pro(u) -> bool:
    if bool(getattr(u, "is_admin", False)):
        return True
    plan = ((getattr(u, "plan", "") or "")).strip().lower()
    if bool(getattr(u, "is_pro", False)):
        return True
    return plan in {"pro", "biz", "business", "empresa", "empresas"}

def require_pro_user(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db=db)
    if not user:
        raise HTTPException(status_code=303, detail="login", headers={"Location": "/auth/login"})
    if not _is_pro(user):
        raise HTTPException(status_code=303, detail="Funcionalidad sólo PRO", headers={"Location": "/billing?upgrade=mail"})
    return user

router = APIRouter(prefix="/mail", tags=["mail"], dependencies=[Depends(require_pro_user)])

# ====== templates ======
APP_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ====== MODELOS ======
# Fuente de verdad: MailAccount vive en app.models (ya está definido allí)
from app.models import MailAccount, User  # 👈 importamos User para buscar el usuario al notificar

# MailAlert sólo existe aquí
class MailAlert(Base):
    __tablename__ = "mail_alerts"

    id        = Column(Integer, primary_key=True)
    user_id   = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    msg_uid   = Column(String, index=True)
    subject   = Column(Text)
    sender    = Column(String)
    reason    = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_read   = Column(Boolean, default=False)

# Crear SOLO las tablas que estén definidas aquí (mail_alerts).  No redefine mail_accounts.
try:
    MailAlert.__table__.create(bind=engine, checkfirst=True)
except Exception as e:
    print(f"[mail] aviso creando tabla mail_alerts: {e}")

# ====== heurísticas ======
SUS_ATTACH_EXTS = {".exe", ".js", ".scr", ".bat", ".cmd", ".vbs", ".html", ".htm", ".zip", ".rar"}
SUS_SUBJECT_WORDS = {"suspend","suspendida","password","contraseña","verify","verificar","urgente","factura","pago","bloqueada","blocked"}

def _decode_hdr(v):
    try:
        return str(make_header(decode_header(v)))
    except Exception:
        return v or ""

def _risky(msg: email.message.Message) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    subj = _decode_hdr(msg.get("Subject", ""))
    if any(w in subj.lower() for w in SUS_SUBJECT_WORDS):
        reasons.append("Asunto sospechoso")
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            fn = part.get_filename()
            if fn:
                fn_d = _decode_hdr(fn).lower()
                for ext in SUS_ATTACH_EXTS:
                    if fn_d.endswith(ext):
                        reasons.append(f"Adjunto peligroso ({ext})")
                        break
    try:
        from bs4 import BeautifulSoup
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html = part.get_payload(decode=True) or b""
                soup = BeautifulSoup(html, "html.parser")  # type: ignore
                for a in soup.find_all("a"):
                    href = (a.get("href") or "").lower()
                    if any(x in href for x in ("bit.ly","tinyurl","goo.gl")):
                        reasons.append("Acortador de URL")
                        break
    except Exception:
        pass
    return (len(reasons) > 0, reasons)

def _imap_login(acct: MailAccount) -> imaplib.IMAP4:
    import json
    f = _get_fernet()
    try:
        data = json.loads(f.decrypt(acct.enc_blob.encode()).decode())
    except Exception:
        raise HTTPException(status_code=500, detail="No se pudo descifrar las credenciales")

    server = acct.imap_server or acct.imap_host or "imap.gmail.com"
    port = acct.imap_port or 993
    M = imaplib.IMAP4_SSL(server, port) if acct.use_ssl else imaplib.IMAP4(server, port)
    M.login(data["username"], data["password"])
    return M

# ====== índice /mail y /mail/ (evita 404) ======
@router.get("", response_class=HTMLResponse, include_in_schema=False)   # /mail
@router.get("/", response_class=HTMLResponse, include_in_schema=False)  # /mail/
def mail_index(_request: Request):
    return RedirectResponse(url="/mail/scanner", status_code=302)

# ====== UI conectar ======
@router.get("/connect", response_class=HTMLResponse)
def connect_form(request: Request):
    return templates.TemplateResponse("mail_connect.html", {"request": request})

@router.post("/connect", response_class=HTMLResponse)
async def connect_submit(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    stage = "init"
    try:
        stage = "parse-body"
        ctype = (request.headers.get("content-type") or "").lower()
        if ctype.startswith("application/json"):
            body = await request.json() or {}
            email_addr  = (body.get("email_addr") or "").strip()
            username    = (body.get("username") or "").strip()
            password    = (body.get("password") or "").strip()
            imap_server = (body.get("imap_server") or "imap.gmail.com").strip()
            imap_port   = int(body.get("imap_port") or 993)
            use_ssl     = str(body.get("use_ssl") or "true").lower() in {"1","true","on","yes"}
        else:
            form = await request.form()
            email_addr  = (form.get("email_addr") or "").strip()
            username    = (form.get("username") or "").strip()
            password    = (form.get("password") or "").strip()
            imap_server = (form.get("imap_server") or "imap.gmail.com").strip()
            imap_port   = int(form.get("imap_port") or 993)
            use_ssl     = bool(form.get("use_ssl"))

        if not email_addr or not username or not password:
            return templates.TemplateResponse(
                "mail_connect.html",
                {"request": request, "error": "Faltan campos (email, usuario o contraseña)."},
                status_code=400,
            )

        # test de login
        try:
            M = imaplib.IMAP4_SSL(imap_server, imap_port) if use_ssl else imaplib.IMAP4(imap_server, imap_port)
            M.login(username, password)
            M.logout()
        except Exception as e:
            return templates.TemplateResponse(
                "mail_connect.html",
                {"request": request, "error": f"Error de conexión IMAP: {e}"},
                status_code=400,
            )

        # cifrado + upsert
        import json
        f = _get_fernet()
        blob = f.encrypt(json.dumps({"username": username, "password": password}).encode()).decode()

        acct = db.query(MailAccount).filter(
            MailAccount.user_id == user.id,
            MailAccount.email == email_addr
        ).first()

        if acct is None:
            acct = MailAccount(
                user_id=user.id,
                email=email_addr,
                imap_host=imap_server,
                imap_server=imap_server,
                imap_port=imap_port,
                use_ssl=use_ssl,
                enc_blob=blob,
                enc_password=blob,
            )
            db.add(acct)
        else:
            acct.imap_host   = imap_server
            acct.imap_server = imap_server
            acct.imap_port   = imap_port
            acct.use_ssl     = use_ssl
            acct.enc_blob    = blob
            acct.enc_password= blob

        db.commit()
        return templates.TemplateResponse("mail_connect.html", {"request": request, "ok": True, "email_addr": email_addr})
    except Exception as e:
        import traceback; traceback.print_exc()
        return templates.TemplateResponse("mail_connect.html", {"request": request, "error": f"Fallo en etapa '{stage}': {e}"}, status_code=500)

# ====== scanner UI ======
@router.get("/scanner", response_class=HTMLResponse)
def manual_scan(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    acct = db.query(MailAccount).filter(MailAccount.user_id == user.id).order_by(MailAccount.id.desc()).first()
    if not acct:
        return RedirectResponse(url="/mail/connect", status_code=302)

    findings: List[Tuple[str, str, List[str]]] = []
    try:
        M = _imap_login(acct)
        M.select("INBOX")
        since = (datetime.utcnow() - timedelta(days=30)).strftime("%d-%b-%Y")
        status, data = M.search(None, f'(SINCE {since})')
        if status != "OK":
            raise RuntimeError("No pude listar correos")

        uids = data[0].split()[-30:]
        for uid in reversed(uids):
            st, msg_data = M.fetch(uid, "(RFC822)")
            if st != "OK" or not msg_data:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            risky, reasons = _risky(msg)
            if risky:
                subject = _decode_hdr(msg.get("Subject", ""))
                sender = _decode_hdr(msg.get("From", ""))
                findings.append((subject, sender, reasons))

                uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
                exists = db.query(MailAlert).filter(
                    MailAlert.user_id == user.id,
                    MailAlert.msg_uid == uid_str
                ).first()
                if not exists:
                    db.add(MailAlert(user_id=user.id, msg_uid=uid_str, subject=subject, sender=sender, reason="; ".join(reasons)))
                    db.commit()
                    _notify_alert(user_id=user.id, subject=subject, sender=sender, reasons=reasons)
        M.logout()
    except Exception as e:
        return HTMLResponse(f"<h2>Error escaneando: {e}</h2>", status_code=500)

    def _chip_list(rs: List[str]) -> str:
        return "".join(f"<span class='tag'>{r}</span>" for r in rs)

    cards = "".join(
        f"""
        <article class="item">
          <div class="item-head">
            <div class="dot warn"></div>
            <h4 class="subject">{subject or '(sin asunto)'}</h4>
          </div>
          <p class="sender">{sender or ''}</p>
          <div class="tags">{_chip_list(reasons)}</div>
        </article>
        """
        for (subject, sender, reasons) in findings
    )

    empty_state = """
      <div class="empty">
        <div class="icon">✅</div>
        <h4>No encontramos riesgos recientes</h4>
        <p class="muted">Revisamos tus últimos correos. Podés volver a escanear cuando quieras.</p>
      </div>
    """

    html = f"""
    <!doctype html><html lang="es"><meta charset="utf-8">
    <title>Mail Scanner — AlertTrail</title>
    <style>
      :root {{
        --bg:#f7fafc; --panel:#ffffff; --text:#0f172a; --muted:#475569; --line:#e5e7eb;
        --brand:#2563eb; --warn:#f59e0b; --chip:#f1f5f9;
      }}
      *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);
      font:16px/1.45 system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,Arial}}
      .container{{max-width:1100px;margin:0 auto;padding:16px}}
      .topbar{{position:sticky;top:0;background:#fffccf00;backdrop-filter:saturate(1.2) blur(6px);border-bottom:1px solid var(--line)}}
      .topbar-inner{{display:flex;align-items:center;justify-content:space-between;padding:12px 16px}}
      .brand{{display:flex;align-items:center;gap:.55rem;font-weight:800;letter-spacing:.2px}}
      .dot{{width:10px;height:10px;border-radius:999px;background:var(--brand)}}
      .pill{{display:flex;align-items:center;gap:.4rem;background:#eef2ff;color:#1e3a8a;border:1px solid #dbeafe;padding:8px 10px;border-radius:999px;font-weight:600}}
      a.btn,a.btn:visited{{text-decoration:none}}
      h1{{margin:18px 0 6px;font-size:1.6rem}}
      .muted{{color:var(--muted)}}
      .card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px}}
      .actions{{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px}}
      .btn{{display:inline-block;border-radius:10px;padding:10px 14px;font-weight:700;border:1px solid var(--line);background:#fff;color:var(--text)}}
      .btn:hover{{border-color:#cbd5e1;box-shadow:0 0 0 3px #e2e8f0}}
      .btn-primary{{background:var(--brand);color:var(--fff);border:0}}
      .btn-primary:hover{{filter:brightness(1.05)}}
      .list{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-top:12px}}
      .item{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px}}
      .item-head{{display:flex;align-items:center;gap:8px;margin-bottom:4px}}
      .dot.warn{{background:var(--warn);box-shadow:0 0 0 4px rgba(245,158,11,.15)}}
      .subject{{margin:0;font-size:1rem}}
      .sender{{margin:.25rem 0 .5rem;color:var(--muted)}}
      .tags{{display:flex;flex-wrap:wrap;gap:6px}}
      .tag{{background:var(--chip);border:1px solid var(--line);color:var(--muted);border-radius:999px;padding:6px 10px;font-size:.85rem}}
      .empty{{text-align:center;padding:36px 16px;border:1px dashed var(--line);border-radius:16px;background:#fff}}
      .empty .icon{{font-size:36px;margin-bottom:6px}}
      .header-block{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;justify-content:space-between}}
      .account{{color:var(--muted)}}
    </style>

    <header class="topbar">
      <div class="container topbar-inner">
        <div class="brand"><div class="dot"></div><a href="/dashboard" style="color:inherit;text-decoration:none">AlertTrail</a></div>
        <div class="pill">📬 {acct.email}</div>
      </div>
    </header>

    <div class="container">
      <div class="card">
        <div class="header-block">
          <div>
            <h1>Mail Scanner</h1>
            <p class="account">Cuenta conectada: <b>{acct.email}</b></p>
          </div>
          <div class="actions">
            <a class="btn" href="/mail/alerts">Ver alertas guardadas</a>
            <a class="btn" href="/dashboard">Volver</a>
            <a class="btn-primary" href="/mail/scanner">Escanear de nuevo</a>
          </div>
        </div>

        { (cards or empty_state) }
      </div>
      <p class="muted" style="margin-top:14px">Soporte: <a href="mailto:admin.alerttrail@gmail.com" style="color:#2563eb;text-decoration:none">admin.alerttrail@gmail.com</a></p>
    </div>
    </html>
    """
    return HTMLResponse(html)

# ====== alertas ======
@router.get("/alerts", response_class=HTMLResponse)
def list_alerts(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    rows = db.query(MailAlert).filter(MailAlert.user_id == user.id).order_by(MailAlert.created_at.desc()).limit(100).all()
    lis = "".join(
        f"<li><b>{_decode_hdr(r.subject or '')}</b> — <small>{_decode_hdr(r.sender or '')}</small>"
        f"<br><i>{r.reason or ''}</i><br><small>{r.created_at}</small></li>"
        for r in rows
    ) or "<li>Sin alertas</li>"
    return HTMLResponse(f"<h2 style='font-family:system-ui'>Alertas</h2><ul>{lis}</ul><p><a href='/dashboard'>Volver</a></p>")

@router.get("/alerts/unread_count")
def unread_count(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    count = db.query(MailAlert).filter(MailAlert.user_id == user.id, MailAlert.is_read == False).count()
    return {"unread": int(count)}

@router.post("/alerts/mark_all_read")
def mark_all_read(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    db.query(MailAlert).filter(MailAlert.user_id == user.id, MailAlert.is_read == False).update({MailAlert.is_read: True})
    db.commit()

# ====== SSE: stream de alertas en tiempo real ======
@router.get("/alerts/stream")
async def alerts_stream(request: Request, db: Session = Depends(get_db)):
    """
    Emite eventos SSE cuando cambia el conteo de alertas no leídas del usuario.
    El dashboard puede abrir EventSource('/mail/alerts/stream') para recibir 'mail_alert'.
    """
    user = get_current_user_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    async def eventgen():
        try:
            last = db.query(MailAlert).filter(
                MailAlert.user_id == user.id, MailAlert.is_read == False
            ).count()
            while True:
                if await request.is_disconnected():
                    break
                await asyncio.sleep(5)
                curr = db.query(MailAlert).filter(
                    MailAlert.user_id == user.id, MailAlert.is_read == False
                ).count()
                if curr > last:
                    # notificar cantidad nueva (el front refresca /alerts/pending si quiere el detalle)
                    yield f'data: {{"type":"mail_alert","new": {curr - last}}}\n\n'
                    last = curr
        except Exception as e:
            # cerramos el stream silenciosamente
            yield f'data: {{"type":"error","message":"{str(e)}"}}\n\n'

    return StreamingResponse(eventgen(), media_type="text/event-stream")

# ====== cron & API ======
MAIL_CRON_SECRET = os.getenv("MAIL_CRON_SECRET", "")

def _notify_alert(user_id: int, subject: str, sender: str, reasons: List[str]) -> None:
    """
    Encola o envía una push (si el user está habilitado PRO + push) cuando aparece un correo riesgoso.
    """
    msg = f"Correo sospechoso: {subject} — {sender} ({'; '.join(reasons)})"
    db = None
    try:
        # Import perezoso para evitar fallos al importar el módulo si falta algo en otros contextos
        from app.services.pro_alerts import queue_or_push as pro_push  # firma: (db, user, title, body, url)
        db = SessionLocal()
        user = db.query(User).get(user_id)  # SQLAlchemy 1.x
        if user:
            pro_push(db, user, title="Alerta de correo", body=msg, url="/mail/alerts")
    except Exception as e:
        print("[mail][_notify_alert] error:", e)
    finally:
        try:
            if db:
                db.close()
        except Exception:
            pass

def _scan_account(db: Session, acct: MailAccount) -> dict:
    scans = alerts = errors = 0
    try:
        M = _imap_login(acct)
        M.select("INBOX")
        since = (datetime.utcnow() - timedelta(days=30)).strftime("%d-%b-%Y")
        status, data = M.search(None, f'(SINCE {since})')
        if status != "OK":
            raise RuntimeError("No pude listar correos")

        uids = data[0].split()[-30:]
        for uid in reversed(uids):
            st, msg_data = M.fetch(uid, "(RFC822)")
            if st != "OK" or not msg_data:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            risky, reasons = _risky(msg)
            scans += 1
            if risky:
                subject = _decode_hdr(msg.get("Subject", ""))
                sender = _decode_hdr(msg.get("From", ""))
                uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
                exists = db.query(MailAlert).filter(MailAlert.user_id == acct.user_id, MailAlert.msg_uid == uid_str).first()
                if not exists:
                    db.add(MailAlert(user_id=acct.user_id, msg_uid=uid_str, subject=subject, sender=sender, reason="; ".join(reasons)))
                    db.commit()
                    _notify_alert(user_id=acct.user_id, subject=subject, sender=sender, reasons=reasons)
                alerts += 1
        M.logout()
    except Exception as e:
        errors += 1
        print(f"[mail][_scan_account] error: {e}")
    return {"scans": scans, "alerts": alerts, "errors": errors}

def _run_scan_all_accounts(db: Session) -> dict:
    total = {"scans": 0, "alerts": 0, "errors": 0}
    accounts = db.query(MailAccount).all()
    for acct in accounts:
        r = _scan_account(db, acct)
        total["scans"] += r["scans"]
        total["alerts"] += r["alerts"]
        total["errors"] += r["errors"]
    return total

# 👇👇 Agregar en app/routers/mail.py
from sqlalchemy.orm import Session

def scan_all_inboxes(db: Session) -> dict:
    """
    Alias que usa el scheduler. Ejecuta el mismo escaneo que /mail/poll
    sobre TODAS las casillas configuradas.
    """
    return _run_scan_all_accounts(db)


@router.get("/poll")
def mail_poll(secret: str, db: Session = Depends(get_db)):
    if not MAIL_CRON_SECRET:
        raise HTTPException(status_code=503, detail="MAIL_CRON_SECRET no configurado")
    if secret != MAIL_CRON_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    result = _run_scan_all_accounts(db)
    return {"status": "ok", "source": "cron", **result}

@router.api_route("/scan", methods=["GET", "POST"])
def mail_scan_api(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    acct = db.query(MailAccount).filter(MailAccount.user_id == user.id).order_by(MailAccount.id.desc()).first()
    if not acct:
        raise HTTPException(status_code=404, detail="No hay casillas vinculadas")
    result = _scan_account(db, acct)
    return {"status": "ok", "source": "manual", **result}
