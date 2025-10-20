# app/mailer.py
import os, smtplib, ssl
from email.message import EmailMessage

# ====================================================
# Configuración SMTP base
# ====================================================
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_TLS  = (os.getenv("SMTP_TLS", "1").strip().lower() in ("1", "true", "yes", "on"))

FROM_EMAIL = os.getenv("FROM_EMAIL", "no-reply@alerttrail.test")
FROM_NAME  = os.getenv("FROM_NAME", "AlertTrail")

# ====================================================
# Función genérica de envío
# ====================================================
def send_email(to: str, subject: str, body: str, html: str | None = None):
    """Envia un correo genérico con soporte HTML opcional."""
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS):
        raise RuntimeError("SMTP no configurado correctamente (faltan variables).")

    msg = EmailMessage()
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    if SMTP_TLS:
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

# ====================================================
# Función específica: invitaciones a equipos
# ====================================================
def send_invite_email(to_email: str, invite_url: str):
    """
    Envía un correo de invitación con plantilla HTML.
    Usa la misma configuración SMTP que send_email().
    """
    subject = "Invitación a AlertTrail"
    plain = f"Hola!\n\nTe invitaron a unirte a AlertTrail.\nIngresa aquí: {invite_url}\n\n"

    html = f"""
    <div style="font-family:system-ui,Segoe UI,sans-serif;max-width:560px">
      <h2 style="color:#1e293b">Invitación a AlertTrail</h2>
      <p>Te invitaron a unirte al equipo.</p>
      <p>
        <a href="{invite_url}" style="background:#2563eb;color:#fff;
           padding:10px 14px;border-radius:8px;text-decoration:none;">
          Aceptar invitación
        </a>
      </p>
      <p style="font-size:13px;color:#64748b;">
        Si el botón no funciona, copiá este enlace en tu navegador:<br>
        <code>{invite_url}</code>
      </p>
      <hr style="border:none;border-top:1px solid #e2e8f0;margin:16px 0">


      # app/mailer.py  (al final)
def send_payment_confirmation_email(to_email: str, plan: str, expires_iso: str | None):
    subject = f"¡Tu plan {plan} está activo!"
    plain = f"""Hola!

Tu suscripción {plan} quedó activa{f' y vence el {expires_iso}' if expires_iso else ''}.
Gracias por apoyar AlertTrail.

— Equipo AlertTrail
"""
    html = f"""
    <div style="font-family:system-ui,Segoe UI,Roboto,Arial;max-width:560px">
      <h2 style="color:#0f172a;margin:0 0 8px">¡Listo! Plan <span style="color:#2563eb">{plan}</span> activo</h2>
      {"<p>Vencimiento: <b>"+expires_iso+"</b></p>" if expires_iso else ""}
      <p>Ya podés usar todas las funciones PRO.</p>
      <p style="margin-top:14px"><a href="https://www.alerttrail.com/dashboard"
         style="background:#2563eb;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none">Ir al dashboard</a></p>
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0">
      <p style="color:#64748b;font-size:12px">Gracias por apoyar AlertTrail.</p>
    </div>
    """
    send_email(to_email, subject, plain, html)

      <p style="font-size:12px;color:#94a3b8;">Este mensaje fue enviado automáticamente por AlertTrail.</p>
    </div>
    """

    send_email(to_email, subject, plain, html)
