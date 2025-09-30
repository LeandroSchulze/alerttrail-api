# app/mailer.py
import os, smtplib, ssl
from email.message import EmailMessage

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_TLS  = (os.getenv("SMTP_TLS", "1").strip().lower() in ("1","true","yes","on"))
FROM_EMAIL = os.getenv("FROM_EMAIL", "no-reply@alerttrail.test")
FROM_NAME  = os.getenv("FROM_NAME", "AlertTrail")

def send_email(to: str, subject: str, body: str, html: str | None = None):
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
