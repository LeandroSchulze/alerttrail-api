# app/services/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from datetime import datetime
import os

from app.database import SessionLocal

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
    Intenta ubicar la función de escaneo que recorre casillas IMAP y crea alertas.
    Ajustá acá si tu función real está en otro path/nombre.
    """
    try:
        # Preferida: servicio dedicado
        from app.services.mail import scan_all_inboxes
        return scan_all_inboxes
    except Exception:
        pass
    try:
        # Alternativa: algunos proyectos la exportan desde el router
        from app.routers.mail import scan_all_inboxes
        return scan_all_inboxes
    except Exception:
        return None

def _run_mail_scan():
    db: Session = SessionLocal()
    try:
        scan_fn = _find_scan_fn()
        if not scan_fn:
            _state["last_error"] = "No encontré scan_all_inboxes()"
            print("[scheduler] ⚠️ No encontré scan_all_inboxes() (services.mail o routers.mail)")
            return

        print("[scheduler] ▶ Ejecutando escaneo de correo…")
        scan_fn(db)  # debe crear alertas si detecta algo
        _state["runs"] += 1
        _state["last_run"] = datetime.utcnow().isoformat() + "Z"
        _state["last_error"] = None
        print("[scheduler] ✅ Escaneo finalizado")
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

