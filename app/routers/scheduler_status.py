# app/routers/scheduler_status.py
from fastapi import APIRouter
try:
    from app.services.scheduler import scheduler_status
except Exception:
    scheduler_status = lambda: {"started": False, "detail": "import error"}

router = APIRouter(prefix="/internal/scheduler", tags=["scheduler"])

@router.get("/status")
def status():
    return scheduler_status()
