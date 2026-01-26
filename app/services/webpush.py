# app/services/webpush.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from pywebpush import webpush, WebPushException

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
SUBS_FILE = MAIL_DATA_DIR / "push_subscriptions.json"


def _load() -> Dict[str, Any]:
    """
    Carga las suscripciones push desde disco.
    Estructura esperada:
    {
        "user_id": { subscription_object }
    }
    """
    try:
        if not SUBS_FILE.exists():
            return {}
        data = json.loads(SUBS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print("Push load error:", e)
        return {}


def send_push(
    user_id: str,
    title: str,
    body: str,
    url: str = "/mail/scanner"
) -> bool:
    """
    Envía una notificación push a un usuario.
    Devuelve True si se intentó enviar, False si no había datos válidos.
    """

    subs = _load()
    sub = subs.get(str(user_id))
    if not sub:
        print(f"No push subscription for user {user_id}")
        return False

    vapid_private = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    vapid_subject = os.getenv(
        "VAPID_SUBJECT",
        "mailto:admin@alerttrail.com"
    ).strip()

    if not vapid_private:
        print("Missing VAPID_PRIVATE_KEY")
        return False

    payload = {
        "title": title,
        "body": body,
        "data": {
            "url": url
        }
    }

    try:
        webpush(
            subscription_info=sub,
            data=json.dumps(payload),
            vapid_private_key=vapid_private,
            vapid_claims={"sub": vapid_subject},
        )
        return True

    except WebPushException as e:
        print("WebPush error:", e)
        return False

    except Exception as e:
        print("Unexpected push error:", e)
        return False
