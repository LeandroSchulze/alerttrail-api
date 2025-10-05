# app/services/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from app.database import SessionLocal

def _run_mail_scan():
    """Llama a la rutina que escanea casillas y genera alertas."""
    db: Session = SessionLocal()
    try:
        # Intenta importar tu escaneo real (ajusta la función si tu proyecto la tiene en otro lado)
        try:
            from app.services.mail import scan_all_inboxes  # ← si ya existe
            scan_all_inboxes(db)
        except Exception:
            # fallback: algunos proyectos lo exponen en el router
            try:
                from app.routers.mail import scan_all_inboxes  # ← si está en routers
                scan_all_inboxes(db)
            except Exception as e:
                print("[scheduler] No encontré función scan_all_inboxes:", repr(e))
    finally:
        db.close()

_scheduler: BackgroundScheduler | None = None

def start_background_scheduler():
    global _scheduler
    if _scheduler:  # ya iniciado
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    # corre cada 60 segundos
    _scheduler.add_job(_run_mail_scan, IntervalTrigger(seconds=60), id="mail_scan", replace_existing=True)
    _scheduler.start()
    print("[scheduler] Iniciado: mail_scan cada 60s")
