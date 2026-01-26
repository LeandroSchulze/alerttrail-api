import os
import requests

from app.mailer import send_email
from app.services.webpush import send_push

ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip()


def notify_email(to_email: str, subject: str, body: str) -> bool:
    try:
        send_email(to_email, subject, body)
        return True
    except Exception as e:
        print("notify_email error:", e)
        return False


def notify_webhook(payload: dict) -> bool:
    if not ALERT_WEBHOOK_URL:
        return False
    try:
        r = requests.post(ALERT_WEBHOOK_URL, json=payload, timeout=5)
        return 200 <= r.status_code < 300
    except Exception as e:
        print("notify_webhook error:", e)
        return False


def notify_all(
    *,
    user_id: str | None = None,
    to_email: str | None,
    subject: str,
    body: str,
    link: str = "/mail/scanner",
    extra: dict | None = None,
) -> bool:
    """
    Notifica por todos los canales disponibles:
    - Email (si hay to_email)
    - Push (si hay user_id)
    - Webhook (si está configurado)
    """

    ok_any = False

    # Email
    if to_email:
        ok_any |= notify_email(to_email, subject, body)

    # Push (POP-UP)
    if user_id:
        ok_any |= send_push(
            user_id=user_id,
            title=subject,
            body=body,
            url=link,
        )

    # Webhook
    payload = {"subject": subject, "body": body, "link": link}
    if extra:
        payload.update(extra)

    ok_any |= notify_webhook(payload)

    return ok_any
