# app/routers/darkweb.py
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User, DarkwebScanRequest
from app.security import get_current_user_cookie
from datetime import datetime
import os

router = APIRouter(tags=["darkweb"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


BASE_STYLE = """
:root{
  --bg:#020617;
  --bg-soft:#020617;
  --border:#1f2937;
  --text:#e5e7eb;
  --accent:#38bdf8;
  --accent-soft:rgba(56,189,248,.12);
  --danger:#f97373;
  --danger-soft:rgba(248,113,113,.12);
}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(circle at top,#0f172a,#020617);
     font-family:system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;color:var(--text);}
.container{max-width:980px;margin:32px auto;padding:0 16px}
.card{background:rgba(15,23,42,.92);border:1px solid var(--border);
      border-radius:18px;box-shadow:0 18px 60px rgba(15,23,42,.75);padding:20px}
h1{font-size:1.8rem;margin:0 0 8px;color:var(--accent);}
h2{font-size:1.2rem;margin:16px 0 8px;color:#e5e7eb;}
p{margin:4px 0;}
.badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;
       padding:4px 10px;border-radius:999px;
       border:1px solid rgba(56,189,248,.6);background:rgba(8,47,73,.7);color:#e0f2fe;}
.badge span.dot{width:7px;height:7px;border-radius:999px;background:#22c55e;
                box-shadow:0 0 10px rgba(34,197,94,.9);}
.grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);
      gap:18px;margin-top:16px;}
ul{padding-left:18px;margin:6px 0;}
li{margin-bottom:4px;}
.btn-row{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px;}
.btn{padding:10px 14px;border-radius:999px;border:1px solid #1e293b;
     background:#020617;color:#e5e7eb;cursor:pointer;font-size:14px;
     text-decoration:none;display:inline-flex;align-items:center;gap:6px;}
.btn.primary{background:linear-gradient(to right,#0ea5e9,#6366f1);
             border-color:transparent;color:white;}
.btn.primary:hover{filter:brightness(1.05);}
.muted{color:#9ca3af;font-size:14px;}
.chip{display:inline-block;padding:4px 8px;border-radius:999px;
      background:var(--accent-soft);font-size:11px;color:#bae6fd;
      border:1px solid rgba(56,189,248,.3);margin-right:4px;margin-bottom:4px;}
.callout{border-radius:14px;border:1px dashed rgba(148,163,184,.6);
         padding:10px 12px;margin-top:10px;background:rgba(15,23,42,.85);}
.callout strong{color:#e5e7eb;}
"""

PRO_PLANS = {"PRO", "BIZ", "EMPRESA", "EMPRESAS", "ENTERPRISE"}
DARKWEB_REQUEST_EMAIL = os.getenv("DARKWEB_REQUEST_EMAIL", os.getenv("AUDIT_REQUEST_EMAIL", "info.alerttrail@gmail.com"))


def _get_user_plan(request: Request, db: Session) -> str:
    """
    Devuelve el plan del usuario actual en MAYÚSCULAS.
    Si no hay usuario o algo falla, devuelve 'FREE'.
    """
    try:
        payload = get_current_user_cookie(request)
    except Exception:
        return "FREE"

    try:
        user_id = payload.get("sub")
        if not user_id:
            return "FREE"
        u = db.query(User).filter(User.id == user_id).first()
        if not u:
            return "FREE"
        return (getattr(u, "plan", None) or "FREE").upper()
    except Exception:
        return "FREE"


@router.get("/darkweb", include_in_schema=False, response_class=HTMLResponse)
@router.get("/darkweb/", include_in_schema=False, response_class=HTMLResponse)
def darkweb_radar_page(request: Request, db: Session = Depends(get_db)):
    plan = _get_user_plan(request, db)
    pro_like = {"PRO", "BIZ", "EMPRESA", "EMPRESAS", "ENTERPRISE"}

    is_pro = plan in pro_like

    if is_pro:
        badge = "Incluido en tu plan PRO / EMPRESAS"
        subtitle = "Vista previa del monitor de filtraciones incluido en tu cuenta."
        state_text = (
            "Tu cuenta PRO ya está marcada para acceder a este módulo cuando lo "
            "liberemos. Mientras tanto, podés usar esta pantalla para explicar a tu "
            "equipo qué hace Dark Web Radar."
        )
        cta_label = "Ver tu suscripción"
    else:
        badge = "Próximamente en AlertTrail"
        subtitle = "Previsualización del módulo Dark Web Radar."
        state_text = (
            "Esta es una vista previa del módulo de monitoreo de filtraciones en la "
            "dark web. Primero lo vamos a lanzar para cuentas PRO y EMPRESAS."
        )
        cta_label = "Ver planes"

    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Dark Web Radar — AlertTrail</title>
<style>{BASE_STYLE}</style>
<body>
<div class="container">
  <div class="card">
    <div class="badge"><span class="dot"></span> {badge}</div>
    <h1>Dark Web Radar</h1>
    <p class="muted">{subtitle}</p>

    <div class="grid">
      <div>
        <h2>¿Qué va a hacer esta función?</h2>
        <p>La idea es que Dark Web Radar te avise si aparecen credenciales o datos sensibles
        vinculados a tus correos o dominios en foros, dumps o mercados de la dark web.</p>
        <ul>
          <li>Revisión de correos corporativos en listas de credenciales filtradas.</li>
          <li>Detección de dominios/servicios mencionados en foros de acceso ilícito.</li>
          <li>Alertas por exposiciones nuevas detectadas por nuestros monitores.</li>
        </ul>

        <div class="callout">
          <strong>Primero para PRO / Empresas.</strong><br>
          La versión inicial se enfocará en organizaciones que manejan datos sensibles,
          con un alcance acotado pero útil para auditorías periódicas.
        </div>
      </div>
      <div>
        <h2>Alcance pensado</h2>
        <p class="muted">No vamos a indexar toda la dark web. La idea es:</p>
        <ul>
          <li>Monitorizar fuentes específicas de mayor riesgo (foros/dumps).</li>
          <li>Enfocarnos en coincidencias concretas con tus activos (correos, dominios).</li>
          <li>Entregar reportes claros que puedas compartir con tu equipo.</li>
        </ul>
        <h2 style="margin-top:16px;">Estado actual</h2>
        <p class="muted">
          No hay escaneo real en esta versión, pero la integración ya está preparada
          para activarse primero en cuentas PRO y EMPRESAS.
        </p>
      </div>
    </div>
  </div>
</div>
</body>
"""
    return HTMLResponse(html)


def _get_user_and_plan(request: Request, db: Session):
    """
    Helper para obtener (user, plan) usando la cookie.
    Reutiliza la lógica de _get_user_plan y luego busca el usuario.
    """
    plan = _get_user_plan(request, db)
    user = None
    try:
        payload = get_current_user_cookie(request)
        user_id = payload.get("sub") if payload else None
        if user_id:
            user = db.query(User).filter(User.id == user_id).first()
    except Exception:
        user = None
    return user, plan


@router.get("/darkweb/request", include_in_schema=False, response_class=HTMLResponse)
def darkweb_request_page(request: Request, db: Session = Depends(get_db)):
    user, plan = _get_user_and_plan(request, db)
    is_pro = plan in PRO_PLANS

    if not is_pro:
        html = f"""<!doctype html>
<meta charset="utf-8">
<title>Dark Web Radar — Solo para cuentas PRO</title>
<style>{BASE_STYLE}</style>
<body>
<div class="container">
  <div class="card">
    <div class="badge"><span class="dot"></span> Solo PRO / Empresas</div>
    <h1>Escaneo en Dark Web</h1>
    <p class="muted">
      Este servicio de escaneo manual asistido por IA está disponible únicamente
      para cuentas PRO y EMPRESAS. Tu plan actual es: <b>{plan}</b>.
    </p>
    <p class="muted">
      Si querés acceder a este servicio, mejorá tu suscripción desde la sección de
      facturación.
    </p>
    <div class="btn-row" style="margin-top:16px;">
      <a href="/billing" class="btn primary">Ver planes y suscripción</a>
      <a href="/dashboard" class="btn">Volver al dashboard</a>
    </div>
  </div>
</div>
</body>
"""
        return HTMLResponse(html, status_code=403)

    contact_email = (user.email if user and getattr(user, "email", None) else "")

    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Solicitud de escaneo en Dark Web — AlertTrail</title>
<style>{BASE_STYLE}</style>
<body>
<div class="container">
  <div class="card">
    <div class="badge"><span class="dot"></span> Servicio manual para cuentas PRO</div>
    <h1>Solicitar escaneo en Dark Web</h1>
    <p class="muted">
      Completá este formulario y vamos a realizar un escaneo manual (en un entorno
      aislado) buscando filtraciones relacionadas con tus correos y dominios.
      Luego te enviaremos un informe detallado por correo.
    </p>

    <form method="post" action="/darkweb/request" style="margin-top:16px;display:flex;flex-direction:column;gap:10px;">
      <div>
        <label>Nombre de contacto</label><br>
        <input name="who" placeholder="Ej: Responsable de TI" style="width:100%;padding:8px;border-radius:8px;border:1px solid #1f2933;background:#020617;color:#e5e7eb">
      </div>
      <div>
        <label>Correo de contacto</label><br>
        <input name="contact_email" type="email" required value="{contact_email}" placeholder="tu@empresa.com" style="width:100%;padding:8px;border-radius:8px;border:1px solid #1f2933;background:#020617;color:#e5e7eb">
      </div>
      <div>
        <label>Correos a revisar</label>
        <p class="muted">Uno por línea. Ej: cuentas críticas de la empresa.</p>
        <textarea name="targets_emails" rows="3" placeholder="seguridad@empresa.com&#10;finanzas@empresa.com" style="width:100%;padding:8px;border-radius:8px;border:1px solid #1f2933;background:#020617;color:#e5e7eb"></textarea>
      </div>
      <div>
        <label>Dominios / servicios a revisar</label>
        <p class="muted">Ej: dominio corporativo, VPN, portales internos, etc.</p>
        <textarea name="targets_domains" rows="2" placeholder="empresa.com&#10;vpn.empresa.com" style="width:100%;padding:8px;border-radius:8px;border:1px solid #1f2933;background:#020617;color:#e5e7eb"></textarea>
      </div>
      <div>
        <label>Palabras clave / marca</label>
        <textarea name="keywords" rows="2" placeholder="Nombre de la marca, productos internos, etc." style="width:100%;padding:8px;border-radius:8px;border:1px solid #1f2933;background:#020617;color:#e5e7eb"></textarea>
      </div>
      <div>
        <label>Notas adicionales</label>
        <textarea name="notes" rows="3" placeholder="Contexto adicional, prioridad, restricciones, etc." style="width:100%;padding:8px;border-radius:8px;border:1px solid #1f2933;background:#020617;color:#e5e7eb"></textarea>
      </div>

      <div class="btn-row" style="margin-top:10px;">
        <button class="btn primary" type="submit">Enviar solicitud</button>
        <a href="/dashboard" class="btn">Cancelar</a>
      </div>
    </form>
  </div>
</div>
</body>
"""
    return HTMLResponse(html)


@router.post("/darkweb/request", include_in_schema=False, response_class=HTMLResponse)
def darkweb_request_submit(
    request: Request,
    who: str = Form(""),
    contact_email: str = Form(...),
    targets_emails: str = Form(""),
    targets_domains: str = Form(""),
    keywords: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user, plan = _get_user_and_plan(request, db)
    is_pro = plan in PRO_PLANS

    if not is_pro:
        html = f"""<!doctype html>
<meta charset="utf-8">
<title>Dark Web Radar — Solo PRO</title>
<style>{BASE_STYLE}</style>
<body>
<div class="container">
  <div class="card">
    <h1>Solicitud no permitida</h1>
    <p class="muted">
      Este servicio está disponible solo para cuentas PRO / EMPRESAS. Tu plan actual es: <b>{plan}</b>.
    </p>
    <div class="btn-row" style="margin-top:16px;">
      <a href="/billing" class="btn primary">Ver planes</a>
      <a href="/dashboard" class="btn">Volver al dashboard</a>
    </div>
  </div>
</div>
</body>
"""
        return HTMLResponse(html, status_code=403)

    user_id = user.id if user is not None else None

    req_obj = DarkwebScanRequest(
        user_id=user_id,
        contact_name=who.strip() or None,
        contact_email=contact_email.strip(),
        targets_emails=targets_emails.strip() or None,
        targets_domains=targets_domains.strip() or None,
        keywords=keywords.strip() or None,
        notes=notes.strip() or None,
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(req_obj)
    db.commit()
    db.refresh(req_obj)

    # Intentar enviar un correo interno para avisarte de la nueva solicitud
    send_ok = True
    error_msg = ""
    try:
        from app.mailer import send_email

        subject = "Nueva solicitud de escaneo en Dark Web — AlertTrail"
        body_lines = [
            f"ID solicitud: {req_obj.id}",
            f"Contacto: {who or '(sin nombre)'}",
            f"Correo de contacto: {contact_email}",
            f"Usuario AlertTrail: {user.email if user else '(no autenticado)'}",
            "",
            "Correos a revisar:",
            targets_emails or "(sin correos)",
            "",
            "Dominios / servicios:",
            targets_domains or "(sin dominios)",
            "",
            "Palabras clave:",
            keywords or "(sin keywords)",
            "",
            "Notas adicionales:",
            notes or "(sin notas)",
        ]
        plain = "\n".join(body_lines)
        html_body = "<br>".join(line.replace(" ", "&nbsp;") for line in body_lines)
        send_email(DARKWEB_REQUEST_EMAIL, subject, plain, html_body)
    except Exception as e:
        send_ok = False
        error_msg = str(e)

    status_text = "¡Solicitud enviada!" if send_ok else "Solicitud registrada (con advertencia)"
    extra_msg = (
        "Vamos a revisar tu solicitud y te enviaremos el informe por correo cuando esté listo."
        if send_ok
        else "Registramos tu solicitud, pero no pudimos enviar el correo interno automático. Revisaremos las solicitudes pendientes desde el panel de administración."
    )

    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Solicitud enviada — Dark Web Radar</title>
<style>{BASE_STYLE}</style>
<body>
<div class="container">
  <div class="card">
    <h1>{status_text}</h1>
    <p class="muted">
      {extra_msg}
    </p>
    <p class="muted">
      Te vamos a escribir a <b>{contact_email}</b> cuando tengamos el informe del escaneo.
      ID de tu solicitud: <b>{req_obj.id}</b>.
    </p>
    {("<p class='muted' style='margin-top:12px;color:#b91c1c'>Error al enviar correo interno: " + error_msg + "</p>") if not send_ok else ""}
    <div class="btn-row" style="margin-top:16px;">
      <a href="/dashboard" class="btn">Volver al dashboard</a>
    </div>
  </div>
</div>
</body>
"""
    return HTMLResponse(html)
