import os, requests
from app.mailer import send_email

ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip()

def notify_email(to_email: str, subject: str, body: str):
    try:
        send_email(to_email, subject, body)
        return True
    except Exception as e:
        print("notify_email error:", e)
        return False

def notify_webhook(payload: dict):
    if not ALERT_WEBHOOK_URL:
        return False
    try:
        r = requests.post(ALERT_WEBHOOK_URL, json=payload, timeout=5)
        return 200 <= r.status_code < 300
    except Exception as e:
        print("notify_webhook error:", e)
        return False

def notify_all(to_email: str | None, subject: str, body: str, link: str = "", extra: dict | None = None):
    ok_any = False
    if to_email:
        ok_any |= notify_email(to_email, subject, body)
    payload = {"subject": subject, "body": body, "link": link}
    if extra:
        payload.update(extra)
    ok_any |= notify_webhook(payload)
    return ok_any
