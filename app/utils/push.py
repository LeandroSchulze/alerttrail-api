# app/utils/push.py
import os
import json
from pywebpush import webpush, WebPushException

VAPID_PUBLIC_KEY = (os.getenv("VAPID_PUBLIC_KEY") or "").strip()
VAPID_PRIVATE_KEY = (os.getenv("VAPID_PRIVATE_KEY") or "").strip()

VAPID_CLAIMS = {
    "sub": os.getenv("VAPID_SUB", "mailto:admin@alerttrail.com")
}


def get_vapid_public_key() -> str:
    """
    Devuelve la VAPID public key o string vacío si no está configurada.
    El frontend maneja el caso vacío sin romper.
    """
    return VAPID_PUBLIC_KEY


def send_web_push(subscription: dict, payload: dict) -> bool:
    """
    Envía un push notification.
    Retorna True si fue enviado correctamente.
    Nunca levanta excepción hacia arriba.
    """
    if not VAPID_PRIVATE_KEY:
        print("[Push] VAPID_PRIVATE_KEY missing, push skipped")
        return False

    if not subscription:
        print("[Push] Empty subscription, push skipped")
        return False

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=VAPID_CLAIMS,
        )
        return True

    except WebPushException as ex:
        print("[Push] WebPush error:", repr(ex))
        return False

    except Exception as ex:
        print("[Push] Unexpected error:", repr(ex))
        return False
