# app/utils/push.py
import os, json
from pywebpush import webpush, WebPushException

VAPID_PUBLIC_KEY  = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS = {"sub": "mailto:admin@alerttrail.com"}

def get_vapid_public_key() -> str:
    return VAPID_PUBLIC_KEY or ""

def send_web_push(subscription: dict, payload: dict) -> bool:
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=VAPID_CLAIMS
        )
        return True
    except WebPushException as ex:
        print("WebPush error:", ex)
        return False
