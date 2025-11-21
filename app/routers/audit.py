from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse
import os
from typing import Any

from app.security import get_current_user_cookie

router = APIRouter(prefix="/audit", tags=["audit"])

AUDIT_EMAIL_TO = os.getenv("AUDIT_REQUEST_EMAIL", "info.alerttrail@gmail.com")


def _get_user_email(user: Any) -> str:
    if user is None:
        return ""
    if isinstance(user, dict):
        return str(user.get("email") or "")
    return str(getattr(user, "email", "") or "")


@router.get("/", response_class=HTMLResponse)
def audit_landing(request: Request, user=Depends(get_current_user_cookie)) -> HTMLResponse:
    user_email = _get_user_email(user)
    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Auditoría de ciberseguridad — AlertTrail</title>
  <link rel="stylesheet" href="/static/style.css">
  <style>
    body {{ background: var(--bg); }}
    .audit-page {{ max-width: 960px; margin: 32px auto; padding: 0 16px 40px; }}
    .audit-grid {{ display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 16px; }}
    .audit-section-title {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; }}
    .audit-section-title h1 {{ font-size: 26px; margin:0; }}
    .pill-pro {{ display:inline-flex; align-items:center; padding:2px 10px; border-radius:999px;
                 font-size:11px; font-weight:600; background:#dbeafe; color:#1d4ed8; }}
    .audit-muted {{ color: var(--muted); font-size:14px; }}
    .audit-card-title {{ font-size:18px; font-weight:600; margin-bottom:4px; }}
    .audit-list {{ margin:8px 0 0 18px; padding:0; color:var(--muted); font-size:14px; }}
    .audit-list li {{ margin-bottom:4px; }}
    .audit-label {{ font-size:13px; font-weight:500; color:#0f172a; margin-bottom:4px; }}
    .audit-input, .audit-textarea, .audit-select {{
        width:100%; border-radius:10px; border:1px solid var(--border);
        padding:8px 10px; font:inherit; color:var(--text); background:#fff;
    }}
    .audit-textarea {{ min-height:90px; resize:vertical; }}
    .audit-input:focus, .audit-textarea:focus, .audit-select:focus {{
        outline:2px solid var(--accent); outline-offset:1px; border-color:var(--accent);
    }}
    .audit-row {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:12px; }}
    .audit-help {{ font-size:12px; color:var(--muted); margin-top:4px; }}
    @media (max-width: 880px) {{
        .audit-grid {{ grid-template-columns: minmax(0,1fr); }}
    }}
  </style>
</head>
<body>
  <div class="audit-page">
    <div class="card">
      <div class="audit-section-title">
        <h1>Auditoría de ciberseguridad</h1>
        <span class="pill-pro">Servicio extra para cuentas PRO / Empresas</span>
      </div>
      <p class="audit-muted">
        Te ayudamos a revisar tu entorno (correos, accesos, configuraciones básicas) y te entregamos
        un checklist accionable con los próximos pasos para reducir riesgos.
      </p>
      <div class="audit-grid" style="margin-top:16px">
        <div>
          <div class="audit-card-title">¿Qué incluye esta auditoría?</div>
          <ul class="audit-list">
            <li>Revisión de cómo usás AlertTrail (logs, correo, alertas) y recomendaciones rápidas.</li>
            <li>Chequeo básico de buenas prácticas: contraseñas, 2FA, accesos compartidos.</li>
            <li>Ideas de mejoras para tus correos e infraestructura actual (en lenguaje no técnico).</li>
            <li>1 sesión de revisión por videollamada o email (a acordar según tu disponibilidad).</li>
          </ul>
          <p class="audit-help" style="margin-top:10px">
            La auditoría es manual, hecha por una persona real, asistida por IA y herramientas de AlertTrail.
          </p>
        </div>
        <div>
          <div class="audit-card-title">Solicitar una auditoría</div>
          <p class="audit-muted">Completá este formulario y te vamos a responder por mail con la propuesta.</p>
          <form method="post" action="/audit/request" style="display:grid;gap:10px;margin-top:8px">
            <div>
              <div class="audit-label">Tu nombre y organización</div>
              <input class="audit-input" name="who" placeholder="Ej: Laura — Estudio Contable XYZ" required>
            </div>
            <div>
              <div class="audit-label">Correo de contacto</div>
              <input class="audit-input" type="email" name="contact_email" placeholder="tucorreo@dominio.com" value="{user_email}" required>
              <div class="audit-help">Usamos este correo para enviarte la propuesta y coordinar la auditoría.</div>
            </div>
            <div>
              <div class="audit-label">Qué te gustaría revisar</div>
              <textarea class="audit-textarea" name="scope" placeholder="Ej: Correos sospechosos que recibe el equipo comercial, accesos a paneles de administración, logs del servidor, etc."></textarea>
            </div>
            <div>
              <div class="audit-label">Tamaño aproximado del equipo</div>
              <select class="audit-select" name="team_size">
                <option value="1-5">1–5 personas</option>
                <option value="6-20">6–20 personas</option>
                <option value="21-50">21–50 personas</option>
                <option value="51-200">51–200 personas</option>
                <option value="200+">Más de 200</option>
              </select>
            </div>
            <div>
              <div class="audit-label">Comentarios adicionales (opcional)</div>
              <textarea class="audit-textarea" name="notes" placeholder="Links, dominios, sistemas internos, horarios preferidos, etc."></textarea>
            </div>
            <div class="audit-row">
              <button class="btn" type="submit">Enviar solicitud</button>
              <a href="/dashboard" class="btn secondary">Volver al dashboard</a>
            </div>
            <p class="audit-help">
              Precio estimado: te vamos a pasar una propuesta especial para cuentas PRO, mucho más económica
              que una auditoría tradicional del mercado.
            </p>
          </form>
        </div>
      </div>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(html)


@router.post("/request", response_class=HTMLResponse)
def audit_request(
    request: Request,
    who: str = Form(...),
    contact_email: str = Form(...),
    scope: str = Form(""),
    team_size: str = Form(""),
    notes: str = Form(""),
    user=Depends(get_current_user_cookie),
) -> HTMLResponse:
    user_email = _get_user_email(user)
    subject = "Nueva solicitud de auditoría — AlertTrail"
    body_lines = [
        f"Solicitante: {who}",
        f"Correo de contacto: {contact_email}",
        f"Tamaño del equipo: {team_size}",
        "",
        "Alcance deseado:",
        scope or "(sin detalle)",
        "",
        "Comentarios adicionales:",
        notes or "(sin comentarios)",
        "",
        f"Usuario autenticado en AlertTrail: {user_email or 'N/D'}",
    ]
    plain = "\n".join(body_lines)
    html_body = "<br>".join(line.replace(" ", "&nbsp;") for line in body_lines)

    send_ok = True
    error_msg = ""
    try:
        from app.mailer import send_email
        send_email(AUDIT_EMAIL_TO, subject, plain, html_body)
    except Exception as e:
        send_ok = False
        error_msg = str(e)

    status_text = "¡Solicitud enviada!" if send_ok else "Recibimos tu solicitud (con advertencia)"
    extra_msg = (
        "Te vamos a responder a ese correo con la propuesta y próximos pasos."
        if send_ok
        else "No pudimos enviar el correo automáticamente. Copiá el texto de abajo y mandalo a info.alerttrail@gmail.com."
    )

    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Auditoría de ciberseguridad — AlertTrail</title>
  <link rel="stylesheet" href="/static/style.css">
  <style>
    body {{ background: var(--bg); }}
    .audit-page {{ max-width: 720px; margin: 32px auto; padding: 0 16px 40px; }}
    .audit-muted {{ color: var(--muted); font-size:14px; }}
    pre {{
      background:#0f172a0d;
      border-radius:12px;
      padding:12px 14px;
      font-size:12px;
      overflow-x:auto;
      border:1px solid var(--border);
      white-space:pre-wrap;
    }}
  </style>
</head>
<body>
  <div class="audit-page">
    <div class="card">
      <h1 style="font-size:24px;margin:0 0 8px">{status_text}</h1>
      <p class="audit-muted">
        Gracias, <b>{who}</b>. Registramos tu interés en una auditoría de ciberseguridad.
      </p>
      <p class="audit-muted">
        Vamos a escribirte a <b>{contact_email}</b>. {extra_msg}
      </p>
      {"<p class='audit-muted' style='margin-top:12px'><b>Detalle enviado:</b></p><pre>"+plain+"</pre>" if not send_ok else ""}
      {"<p class='audit-muted' style='margin-top:12px;color:#b91c1c'>Error técnico: "+error_msg+"</p>" if not send_ok else ""}
      <div style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap">
        <a href="/dashboard" class="btn">Volver al dashboard</a>
      </div>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(html)
