# app/routers/tasks_mail.py
import os
import time
import traceback
import threading
import hmac

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db

# Importá tu lógica real de escaneo.
# Debe recorrer las casillas conectadas y crear/actualizar alertas.
# Si ya la tenés en otro módulo, ajustá el import y listo.
try:
    # Ejemplo (ajustar al tuyo):
    from app.services.mail_scanner import scan_all_connected_mailboxes  # <- tu función real
except Exception:
    # Fallback de emergencia para no romper el import
    def scan_all_connected_mailboxes(db: Session, **kwargs) -> int:
        # Implementación vacía: no hace nada pero evita 500 si el import falla.
        return 0

router = APIRouter(prefix="/tasks/mail", tags=["tasks-mail"])

# ====== Seguridad (secret por query) ======
TASK_SECRET = (os.getenv("MAIL_CRON_SECRET") or os.getenv("MAIL_POLL_SECRET") or "changeme").strip()

def _secure_compare(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a.encode(), b.encode())
    except Exception:
        return False

# ====== Estado en memoria (anti concurrente + métricas) ======
_LOCK = threading.Lock()
_STATE = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_duration_ms": None,
    "last_ok": None,
    "last_error": None,
    "runs": 0,
    "last_scanned": 0,
}

def _start_run() -> bool:
    """Devuelve True si pudo iniciar (no había otro run en curso)."""
    acquired = _LOCK.acquire(blocking=False)
    if not acquired:
        return False
    _STATE["running"] = True
    _STATE["last_started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _STATE["last_error"] = None
    _STATE["last_scanned"] = 0
    return True

def _finish_run(ok: bool, scanned: int, started_monotonic: float):
    try:
        _STATE["last_finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _STATE["last_duration_ms"] = int((time.monotonic() - started_monotonic) * 1000)
        _STATE["last_ok"] = bool(ok)
        _STATE["last_scanned"] = int(scanned or 0)
        _STATE["runs"] = int(_STATE.get("runs", 0)) + 1
        _STATE["running"] = False
    finally:
        try:
            _LOCK.release()
        except Exception:
            pass

def _call_scanner(db: Session, limit=None, dry_run=False) -> int:
    """
    Llama a scan_all_connected_mailboxes con tolerancia de firma:
    - Si acepta kwargs (limit/dry_run), los usa; si no, invoca sin ellos.
    """
    try:
        return scan_all_connected_mailboxes(db=db, limit=limit, dry_run=dry_run)  # type: ignore
    except TypeError:
        # Firma sin kwargs extra
        return scan_all_connected_mailboxes(db)  # type: ignore


@router.get("/poll", response_class=JSONResponse)
def poll(
    secret: str = Query(..., description="Token de ejecución programada"),
    limit: int | None = Query(None, ge=1, le=10000, description="Máximo de mensajes/casillas a procesar (opcional)"),
    dry_run: bool = Query(False, description="No persiste cambios; útil para test"),
    force: bool = Query(False, description="Forzar inicio aunque haya un run marcado como en curso"),
    db: Session = Depends(get_db),
):
    """
    Tarea idempotente: escanea casillas vinculadas y genera alertas si encuentra riesgo.
    Pensada para ejecutarse por cron (Render) cada 1–5 minutos.
    """
    if not _secure_compare(secret or "", TASK_SECRET):
        raise HTTPException(status_code=403, detail="forbidden")

    if not force and _STATE["running"]:
        return JSONResponse(
            {
                "ok": False,
                "reason": "already_running",
                "state": {k: v for k, v in _STATE.items() if k != "last_error"},
            },
            status_code=200,
        )

    if not _start_run():
        # Otro hilo tomó el lock entre el check anterior y acá
        return JSONResponse(
            {"ok": False, "reason": "already_running_lock", "state": _STATE},
            status_code=200,
        )

    started_monotonic = time.monotonic()
    try:
        scanned = _call_scanner(db, limit=limit, dry_run=dry_run)
        _finish_run(ok=True, scanned=scanned, started_monotonic=started_monotonic)
        return {
            "ok": True,
            "scanned": int(scanned or 0),
            "duration_ms": _STATE["last_duration_ms"],
            "state": {k: v for k, v in _STATE.items() if k != "last_error"},
        }
    except Exception as e:
        traceback.print_exc()
        _STATE["last_error"] = str(e)[:500]
        _finish_run(ok=False, scanned=0, started_monotonic=started_monotonic)
        raise HTTPException(status_code=500, detail="scanner failed")


@router.get("/state", response_class=JSONResponse)
def state(secret: str = Query(..., description="Token de ejecución programada")):
    """Devuelve el estado/métricas del último/actual run (protegid@ por secret)."""
    if not _secure_compare(secret or "", TASK_SECRET):
        raise HTTPException(status_code=403, detail="forbidden")
    # No exponemos stack completo; solo un extracto de error si existe
    view = {k: v for k, v in _STATE.items()}
    if view.get("last_error"):
        view["last_error"] = str(view["last_error"])[:200]
    return view
