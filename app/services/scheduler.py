# app/services/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from datetime import datetime
import os

from app.database import SessionLocal
from sqlalchemy import func

_scheduler = None
_state = {
    "started": False,
    "interval_s": None,
    "last_run": None,
    "runs": 0,
    "last_error": None,
}

def _find_scan_fn():
    """
    Intentamos ubicar la función real de escaneo.
    Ajustá acá si tu función se llama distinto o vive en otro módulo.
    """
    try:
        from app.services.mail import scan_all_inboxes  # <— si existe
        return scan_all_inboxes
    except Exception:
        pass
    try:
        from app.routers.mail import scan_all_inboxes  # <— si la exponen desde el router
        return scan_all_inboxes
    except Exception:
        return None

def _heartbeat_push(db: Session):
    """
    Envía un push de 'heartbeat' para demostrar que el scheduler corrió,
    incluso si no tenemos aún la función de escaneo cableada.
    """
    target_email = os.getenv("SCHEDULER_HEARTBEAT_EMAIL", "")
    if not target_email:
        return False  # desactivado si no hay destino

    try:
        from app.models import User
        from app.routers.push import send_push_to_user  # ya lo tenés en tu proyecto
    except Exception:
        return False

    user = db.query(User).filter(func.lower(User.email) == target_email.strip().lower()).first()
    if not user:
        return False

    payload = {
        "title": "AlertTrail — Heartbeat",
        "body": "El scheduler corrió correctamente.",
        "url": "/dashboard",
        "tag": "alerttrail-heartbeat"
    }
    try:
        send_push_to_user(db, user.id, payload)
        return True
    except Exception:
        return False

def _run_mail_scan():
    db: Session = SessionLocal()
    try:
        scan_fn = _find_scan_fn()
        print("[scheduler] ▶ Tick… intentando escaneo" if scan_fn else "[scheduler] ▶ Tick… (sin scan_all_inboxes)")

        if scan_fn:
            scan_fn(db)  # <-- tu escaneo real
        else:
            # Sin función de escaneo: mandamos heartbeat (si está configurado)
            hb = _heartbeat_push(db)
            if hb:
                print("[scheduler] (heartbeat) push enviado a SCHEDULER_HEARTBEAT_EMAIL")
            else:
                print("[scheduler] (heartbeat) desactivado o sin destino válido")

        _state["runs"] += 1
        _state["last_run"] = datetime.utcnow().isoformat() + "Z"
        _state["last_error"] = None
        print("[scheduler] ✅ Tick OK")
    except Exception as e:
        _state["last_error"] = repr(e)
        print("[scheduler] ❌ Error en escaneo:", repr(e))
    finally:
        db.close()

def start_background_scheduler():
    global _scheduler
    if _scheduler:
        return _scheduler

    if os.getenv("SCHEDULER_ENABLED", "1").lower() not in ("1", "true", "yes", "on"):
        print("[scheduler] Deshabilitado por SCHEDULER_ENABLED")
        return None

    interval = int(os.getenv("MAIL_SCAN_INTERVAL", "60"))
    _state["interval_s"] = interval

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(_run_mail_scan, IntervalTrigger(seconds=interval),
                  id="mail_scan", replace_existing=True)
    sched.start()

    _scheduler = sched
    _state["started"] = True
    print(f"[scheduler] 🟢 Iniciado: mail_scan cada {interval}s")
    return _scheduler

def scheduler_status():
    return dict(_state)
