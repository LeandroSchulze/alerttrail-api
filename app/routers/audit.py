# app/routers/audit.py

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import TemplateNotFound
from pathlib import Path
from typing import Optional
import os
import json
from datetime import datetime
import smtplib
from email.message import EmailMessage

from app.security import get_current_user_cookie

router = APIRouter(prefix="/audit", tags=["audit"])

# Templates (mismo esquema que main.py)
TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Archivo local de respaldo por si el mail falla o no hay SMTP
DATA_DIR = Path(os.getenv("DATA_DIR", "/var/data"))
AUDIT_FILE = DATA_DIR / "audit_requests.json"


def _ensure_data_dir() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print("[audit] WARN no pude crear DATA_DIR:", e)


def _append_audit_record(record: dict) -> None:
    _ensure_data_dir()
    existing = []
    if AUDIT_FILE.exists():
        try:
            existing = json.loads(AUDIT_FILE.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    existing.append(record)
    try:
        AUDIT_FILE.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print("[audit] WARN no pude escribir audit_requests.json:", e)


def _is_pro_user(user) -> bool:
    try:
        plan = (getattr(user, "plan", None) or "").upper()
    except Exception:
        plan = "FREE"

    # Plan PRO / BIZ / Empresa / Enterprise
    if plan in {"PRO", "BIZ", "EMPRESA", "EMPRESAS", "ENTERPRISE"}:
        return True

    # Flag is_pro en la DB
    if getattr(user, "is_pro", False):
        return True

    # Admin siempre puede pedir auditoría
    if getattr(user, "is_admin", False) or getattr(user, "is_superuser", False):
        return True

    return False


def _send_audit_email(subject: str, body: str, to_email: Optional[str] = None) -> bool:
    """
    Envía el mail usando SMTP_* si están configuradas.
    Si falta algo de SMTP, no rompe nada: solo devuelve False.
    """
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587") or 587)
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    use_tls = (os.getenv("SMTP_TLS", "1").lower() in ("1", "true", "yes", "on"))
    to_addr = to_email or os.getenv("AUDIT_REQUEST_TO", "info.alerttrail@gmail.com")

    if not host or not user or not password:
        print("[audit] SMTP no configurado, guardo solo en archivo.")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=20) as s:
            if use_tls:
                s.starttls()
            s.login(user, password)
            s.send_message(msg)
        print("[audit] Email de auditoría enviado OK a", to_addr)
        return True
    except Exception as e:
        print("[audit] ERROR enviando email:", e)
        return False


@router.get("/", response_class=HTMLResponse)
def audit_form(request: Request, user=Depends(get_current_user_cookie)):
    """
    Página principal de Auditoría de Ciberseguridad.
    - Si NO es PRO: muestra un upsell para que se pase a PRO.
    - Si es PRO (o admin): muestra el formulario.
    """
    is_pro = _is_pro_user(user)
    plan = (getattr(user, "plan", None) or "FREE").upper()

    ctx = {
        "request": request,
        "current_user": user,
        "user": user,
        "is_pro": is_pro,
        "plan": plan,
        "sent": request.query_params.get("ok") == "1",
    }

    try:
        return templates.TemplateResponse("audit.html", ctx)
    except TemplateNotFound:
        # Fallback sencillo si falta el template
        if not is_pro:
            html = f"""<!doctype html><meta charset="utf-8">
            <title>Auditoría de Ciberseguridad - AlertTrail</title>
            <div style="font-family:system-ui;padding:24px;max-width:720px;margin:0 auto;color:#0f172a">
              <h1>Auditoría de Ciberseguridad</h1>
              <p style="color:#64748b">
                La auditoría personalizada está disponible para cuentas <b>PRO</b> o superiores.
              </p>
              <p>Tu plan actual: <b>{plan}</b>.</p>
              <a href="/billing/subscriptions"
                 style="display:inline-block;margin-top:12px;padding:8px 12px;border-radius:999px;
                        background:#0ea5e9;color:#fff;text-decoration:none">
                 Ver planes y activar PRO
              </a>
            </div>"""
            return HTMLResponse(html)

        html = f"""<!doctype html><meta charset="utf-8">
        <title>Auditoría de Ciberseguridad - AlertTrail</title>
        <div style="font-family:system-ui;padding:24px;max-width:720px;margin:0 auto;color:#0f172a">
          <h1>Auditoría de Ciberseguridad</h1>
          <p style="color:#64748b">
            Completá el formulario y te contactamos por mail con los próximos pasos.
          </p>
          <form method="post" action="/audit/request" style="display:grid;gap:8px;margin-top:16px">
            <label>Nombre completo
              <input name="full_name" type="text" required
                     value="{getattr(user, 'name', '') or getattr(user, 'email', '')}"
                     style="width:100%;padding:8px;border-radius:8px;border:1px solid #cbd5f5">
            </label>
            <label>Email de contacto
              <input name="contact_email" type="email" required
                     value="{getattr(user, 'email', '')}"
                     style="width:100%;padding:8px;border-radius:8px;border:1px solid #cbd5f5">
            </label>
            <label>Empresa / Proyecto
              <input name="company" type="text"
                     style="width:100%;padding:8px;border-radius:8px;border:1px solid #cbd5f5">
            </label>
            <label>Sitio web (opcional)
              <input name="website" type="text"
                     style="width:100%;padding:8px;border-radius:8px;border:1px solid #cbd5f5">
            </label>
            <label>Tamaño del equipo (aprox.)
              <select name="team_size"
                      style="width:100%;padding:8px;border-radius:8px;border:1px solid #cbd5f5">
                <option value="1-5">1-5</option>
                <option value="6-20">6-20</option>
                <option value="21-50">21-50</option>
                <option value="51-200">51-200</option>
                <option value="200+">200+</option>
              </select>
            </label>
            <label>¿En qué te gustaría que nos enfoquemos?
              <textarea name="focus" rows="3"
                        style="width:100%;padding:8px;border-radius:8px;border:1px solid #cbd5f5"
                        placeholder="Ej: correos sospechosos, accesos remotos, backups, etc."></textarea>
            </label>
            <label>Mensaje adicional (opcional)
              <textarea name="message" rows="4"
                        style="width:100%;padding:8px;border-radius:8px;border:1px solid #cbd5f5"></textarea>
            </label>
            <button type="submit"
                    style="margin-top:8px;padding:10px 16px;border:none;border-radius:999px;
                           background:#0ea5e9;color:#fff;font-weight:600;cursor:pointer">
              Enviar solicitud
            </button>
          </form>
        </div>"""
        return HTMLResponse(html)


@router.post("/request")
def audit_request(
    request: Request,
    full_name: str = Form(...),
    contact_email: str = Form(...),
    company: str = Form(""),
    website: str = Form(""),
    team_size: str = Form(""),
    focus: str = Form(""),
    message: str = Form(""),
    user=Depends(get_current_user_cookie),
):
    """
    Recibe la solicitud de auditoría y la manda por mail + la guarda en un archivo local.
    """
    if not _is_pro_user(user):
        raise HTTPException(
            status_code=403,
            detail="La auditoría está disponible solo para cuentas PRO o superiores.",
        )

    record = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "user_id": getattr(user, "id", None),
        "user_email": getattr(user, "email", None),
        "user_name": getattr(user, "name", None),
        "full_name": full_name,
        "contact_email": contact_email,
        "company": company,
        "website": website,
        "team_size": team_size,
        "focus": focus,
        "message": message,
        "plan": (getattr(user, "plan", None) or "FREE"),
    }

    # Guardamos primero en archivo como backup
    _append_audit_record(record)

    # Intentamos enviar mail
    body_lines = [
        "Nueva solicitud de Auditoría de Ciberseguridad desde AlertTrail:",
        "",
        f"Usuario: {record['user_name'] or record['user_email']}",
        f"Plan: {record['plan']}",
        f"Nombre completo: {full_name}",
        f"Email de contacto: {contact_email}",
        f"Empresa / Proyecto: {company or '-'}",
        f"Sitio web: {website or '-'}",
        f"Tamaño de equipo: {team_size or '-'}",
        "",
        "Enfoque principal:",
        focus or "-",
        "",
        "Mensaje adicional:",
        message or "-",
        "",
        f"Timestamp: {record['ts']}",
    ]
    body = "\n".join(body_lines)
    _send_audit_email("Nueva solicitud de auditoría AlertTrail", body)

    # Volvemos a la pantalla principal con un pequeño OK
    return RedirectResponse(url="/audit?ok=1", status_code=303)
