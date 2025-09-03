# app/routers/analysis.py (solo la función run_analysis)
from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session
from ..deps import get_current_user, get_db, require_pro
from ..models import Analysis, DownloadMetric
from ..services.analysis import analyze_log, format_result
from ..services.pdf import build_pdf
import os
import base64
from datetime import datetime

router = APIRouter(prefix="/analysis", tags=["analysis"])

@router.post("/run")
def run_analysis(
    raw_log: str | None = Form(None),
    raw_b64: str | None = Form(None),
    title: str = Form("Log Analysis"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    # Permitir enviar logs en Base64 para evitar bloqueos del WAF
    if (not raw_log) and raw_b64:
        try:
            raw_log = base64.b64decode(raw_b64).decode("utf-8", "ignore")
        except Exception:
            raise HTTPException(status_code=400, detail="No se pudo decodificar raw_b64")
    if not raw_log:
        raise HTTPException(status_code=400, detail="Falta raw_log o raw_b64")

    findings = analyze_log(raw_log)
    result = format_result(findings)
    a = Analysis(user_id=user.id, title=title, raw_log=raw_log, result=result)
    db.add(a); db.commit(); db.refresh(a)
    return {"id": a.id, "result": a.result}
