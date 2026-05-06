# app/services/webpush.py
from __future__ import annotations
import json
import os
import logging
from typing import Any # <--- ESTA ES LA LÍNEA QUE FALTABA

from pywebpush import webpush, WebPushException
from app.database import SessionLocal
from app.models import PushSubscription

log = logging.getLogger(__name__)

def send_push(user_id: Any, title: str, body: str, url: str = "/mail/scanner") -> bool:
    db = SessionLocal()
    try:
        # Buscamos todas las suscripciones activas de este usuario
        subs = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
        if not subs:
            return False

        vapid_private = os.getenv("VAPID_PRIVATE_KEY", "").strip()
        claims = {"sub": "mailto:admin@alerttrail.com"}

        payload = json.dumps({
            "title": title,
            "body": body,
            "data": {"url": url}
        })

        for sub in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth}
                    },
                    data=payload,
                    vapid_private_key=vapid_private,
                    vapid_claims=claims
                )
            except WebPushException as ex:
                # Si el navegador dice que la suscripción expiró (404/410), la borramos
                if ex.response and ex.response.status_code in (404, 410):
                    db.delete(sub)
                    db.commit()
        return True
    except Exception as e:
        log.error(f"Error inesperado en push: {e}")
        return False
    finally:
        db.close()
