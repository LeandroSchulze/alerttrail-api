# app/routers/mail.py
import os
import imaplib
import email
from email.header import decode_header, make_header
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import Session

from cryptography.fernet import Fernet, InvalidToken

from app.database import Base, engine, get_db
from app.security import get_current_user_cookie

# ---- PRO guard (mail sólo PRO/BIZ) ----
def _is_pro(u) -> bool:
    # dejar pasar a admin siempre (útil para probar)
    if bool(getattr(u, "is_admin", False)):
        return True

    # normalizar plan: None -> "", quitar espacios y bajar a minúsculas
    plan = ((getattr(u, "plan", "") or "")).strip().lower()

    # compat: booleano heredado o alias de nombres
    if bool(getattr(u, "is_pro", False)):
        return True

    return plan in {"pro", "biz", "business", "empresa", "empresas"}

def require_pro_user(request: Request, db: Session = Depends(get_db)):
    """
    Lee el usuario REAL desde la DB (no sólo claims) y valida PRO/BIZ.
    Si no cumple, redirige a /billing con 303.
    """
    user = get_current_user_cookie(request, db=db)  # <- objeto models.User
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    if not _is_pro(user):
        raise HTTPException(
            status_code=303,
            detail="Funcionalidad disponible sólo para PRO",
            headers={"Location": "/billing?upgrade=mail"},
        )
    return user

router = APIRouter(prefix="/mail", tags=["mail"], dependencies=[Depends(require_pro_user)])

# ---- Templates ----
APP_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ---- Alerta in-app (opcional) ----
try:
    from app.services.pro_alerts import queue_or_push  # type: ignore
except Exception:
    queue_or_push = None  # si no existe el módulo, no rompemos

def _notify_alert(user_id: int, subject: str, sender: str, reasons: List[str]) -> None:
    """Envía alerta in-app si está disponible app.services.pro_alerts.queue_or_push."""
    if not queue_or_push:
        return
    try:
        msg = f"Correo sospechoso: {subject} — {sender} ({'; '.join(reasons)})"
        # Ajustá los campos si tu servicio espera otros nombres
        queue_or_push(user_id=user_id, title="Alerta de correo", message=msg, level="warning")
    except Exception:
        pass

# ---- Cifrado credenciales ----
def _get_fernet() -> Fernet:
    """
    Usa MAIL_CRYPT_KEY (Fernet urlsafe-base64) si está; si no, deriva de JWT_SECRET.
    """
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

# ---- Modelos locales ----
class MailAccount(Base):
    __tablename__ = "mail_accounts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email = Column(String, nullable=False)

    imap_host   = Column(String, nullable=False, default="imap.gmail.com")  # compat legado
    imap_server = Column(String, nullable=False, default="imap.gmail.com")
    imap_port   = Column(Integer, nullable=False, default=993)
    use_ssl     = Column(Boolean, nullable=False, default=True)

    enc_blob     = Column(Text, nullable=False, default="")  # JSON cifrado {username,password}
    enc_password = Column(Text, nullable=False, default="")  # legado (NOT NULL en DBs viejas)

    created_at = Column(DateTime, default=datetime.utcnow)

class MailAlert(Base):
    __tablename__ = "mail_alerts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    msg_uid = Column(String, index=True)
    subject = Column(Text)
    sender = Column(String)
    reason = Column(String)  # si en el futuro querés evitar truncados, cambiá a Text y migra la DB
    created_at = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)

# Crear tablas si no existen
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"[mail] aviso creando tablas: {e}")

# ---- Heurísticas de riesgo ----
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
    # enlaces acortados en HTML
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
    except (InvalidToken, Exception):
        raise HTTPException(status_code=500, detail="No se pudo descifrar las credenciales")

    server = acct.imap_server or acct.imap_host or "imap.gmail.com"
    port = acct.imap_port or 993

    M = imaplib.IMAP4_SSL(server, port) if acct.use_ssl else imaplib.IMAP4(server, port)
    M.login(data["username"], data["password"])
    return M

# ---- Ruta índice para evitar 404 en /mail ----
@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request):
    return RedirectResponse(url="/mail/scanner", status_code=302)

# ---- UI Conectar casilla ----
@router.get("/connect", response_class=HTMLResponse)
def connect_form(request: Request):
    return templates.TemplateResponse("mail_connect.html", {"request": request})

@router.post("/connect", response_class=HTMLResponse)
async def connect_submit(request: Request, db: Session = Depends(get_db)):
    """
    Acepta JSON o FormData:
      JSON: {email_addr, username, password, imap_server?, imap_port?, use_ssl?}
      Form: campos con mismos nombres (use_ssl presente => True)
    """
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

        # Test de login
        stage = "test-imap"
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

        # Cifrado y commit
        stage = "encrypt"
        import json
        f = _get_fernet()
        blob = f.encrypt(json.dumps({"username": username, "password": password}).encode()).decode()

        stage = "db-commit"
        acct = db.query(MailAccount).filter(
            MailAccount.user_id == user.id,
            MailAccount.email == email_addr
        ).first()

        if acct is None:
            acct = MailAccount(
                user_id=user.id,
                email=email_addr,
                imap_host=imap_server,          # compat
                imap_server=imap_server,
                imap_port=imap_port,
                use_ssl=use_ssl,
                enc_blob=blob,
                enc_password=blob,              # compat
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

        return templates.TemplateResponse(
            "mail_connect.html",
            {"request": request, "ok": True, "email_addr": email_addr},
        )

    except Exception as e:
        import traceback; traceback.print_exc()
        return templates.TemplateResponse(
            "mail_connect.html",
            {"request": request, "error": f"Fallo en etapa '{stage}': {e}"},
            status_code=500,
        )

# ---- Escaneo manual UI ----
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
                    db.add(MailAlert(
                        user_id=user.id, msg_uid=uid_str,
                        subject=subject, sender=sender,
                        reason="; ".join(reasons),
                    ))
                    db.commit()
                    _notify_alert(user_id=user.id, subject=subject, sender=sender, reasons=reasons)
        M.logout()
    except Exception as e:
        return HTMLResponse(f"<h2>Error escaneando: {e}</h2>", status_code=500)

    # ---------- UI ----------
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
      .topbar{{position:sticky;top:0;background:#fffccf00;backdrop-filter:saturate(1.2) blur(6px);
              border-bottom:1px solid var(--line)}}
      .topbar-inner{{display:flex;align-items:center;justify-content:space-between;padding:12px 16px}}
      .brand{{display:flex;align-items:center;gap:.55rem;font-weight:800;letter-spacing:.2px}}
      .dot{{width:10px;height:10px;border-radius:999px;background:var(--brand)}}
      .pill{{display:flex;align-items:center;gap:.4rem;background:#eef2ff;color:#1e3a8a;border:1px solid #dbeafe;
            padding:8px 10px;border-radius:999px;font-weight:600}}
      a.btn,a.btn:visited{{text-decoration:none}}
      h1{{margin:18px 0 6px;font-size:1.6rem}}
      .muted{{color:var(--muted)}}
      .card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px}}
      .actions{{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px}}
      .btn{{display:inline-block;border-radius:10px;padding:10px 14px;font-weight:700;border:1px solid var(--line);background:#fff;color:var(--text)}}
      .btn:hover{{border-color:#cbd5e1;box-shadow:0 0 0 3px #e2e8f0}}
      .btn-primary{{background:var(--brand);color:#fff;border:0}}
      .btn-primary:hover{{filter:brightness(1.05)}}
      .list{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-top:12px}}
      .item{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px}}
      .item-head{{display:flex;align-items:center;gap:8px;margin-bottom:4px}}
      .dot.warn{{background:var(--warn);box-shadow:0 0 0 4px rgba(245,158,11,.15)}}
      .subject{{margin:0;font-size:1rem}}
      .sender{{margin:.25rem 0 .5rem;color:var(--muted)}}
      .tags{{display:flex;flex-wrap:wrap;gap:6px}}
      .tag{{background:var(--chip);border:1px solid var(--line);color:var(--muted);
            border-radius:999px;padding:6px 10px;font-size:.85rem}}
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
    </div>
    </html>
    """
    return HTMLResponse(html)

# ---- Vista simple de alertas guardadas ----
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
    count = db.query(MailAlert).filter(
        MailAlert.user_id == user.id,
        MailAlert.is_read == False  # noqa: E712
    ).count()
    return {"unread": int(count)}

@router.post("/alerts/mark_all_read")
def mark_all_read(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    db.query(MailAlert).filter(
        MailAlert.user_id == user.id,
        MailAlert.is_read == False  # noqa: E712
    ).update({MailAlert.is_read: True})
    db.commit()


# ---- Helpers para cron / API ----
MAIL_CRON_SECRET = os.getenv("MAIL_CRON_SECRET", "")

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
                exists = db.query(MailAlert).filter(
                    MailAlert.user_id == acct.user_id,
                    MailAlert.msg_uid == uid_str
                ).first()
                if not exists:
                    db.add(MailAlert(
                        user_id=acct.user_id, msg_uid=uid_str,
                        subject=subject, sender=sender,
                        reason="; ".join(reasons),
                    ))
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

# ---- Endpoint cron seguro ----
@router.get("/poll")
def mail_poll(secret: str, db: Session = Depends(get_db)):
    if not MAIL_CRON_SECRET:
        raise HTTPException(status_code=503, detail="MAIL_CRON_SECRET no configurado")
    if secret != MAIL_CRON_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    result = _run_scan_all_accounts(db)
    return {"status": "ok", "source": "cron", **result}

# ---- Endpoint API manual ----
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
