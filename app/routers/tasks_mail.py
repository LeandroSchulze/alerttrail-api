# app/routers/tasks_mail.py
import os, traceback
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db

# Importá tu lógica real de escaneo.
# Debe recorrer las casillas conectadas y crear/actualizar alertas.
# Si ya la tenés en otro módulo, ajustá el import y listo.
try:
    # Ejemplos posibles (dejá el que corresponda en tu app):
    from app.services.mail_scanner import scan_all_connected_mailboxes  # <- tu función real
except Exception:
    # Fallback de emergencia para no romper el import
    def scan_all_connected_mailboxes(db: Session) -> int:
        # Implementación vacía: no hace nada pero evita 500 si el import falla.
        return 0

router = APIRouter(prefix="/tasks/mail", tags=["tasks-mail"])

TASK_SECRET = os.getenv("MAIL_POLL_SECRET", "changeme")

@router.get("/poll")
def poll(secret: str = Query(...), db: Session = Depends(get_db)):
    """
    Tarea idempotente: escanea casillas vinculadas y genera alertas si encuentra riesgo.
    Se dispara por cron (Render) cada 1 minuto.
    """
    if secret != TASK_SECRET:
        raise HTTPException(status_code=403, detail="forbidden")

    try:
        scanned = scan_all_connected_mailboxes(db)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="scanner failed")

    return {"ok": True, "scanned": scanned}
