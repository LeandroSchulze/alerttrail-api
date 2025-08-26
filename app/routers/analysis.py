from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session
from ..deps import get_current_user, get_db, require_pro
from ..models import Analysis, DownloadMetric
from ..services.analysis import analyze_log, format_result
from ..services.pdf import build_pdf
import os
from datetime import datetime

router = APIRouter(prefix="/analysis", tags=["analysis"])

@router.post("/run")
def run_analysis(raw_log: str = Form(...), title: str = Form("Log Analysis"), db: Session = Depends(get_db), user=Depends(get_current_user)):
    findings = analyze_log(raw_log)
    result = format_result(findings)
    a = Analysis(user_id=user.id, title=title, raw_log=raw_log, result=result)
    db.add(a); db.commit(); db.refresh(a)
    return {"id": a.id, "result": a.result}

@router.post("/pdf/{analysis_id}")
def generate_pdf(analysis_id: int, db: Session = Depends(get_db), user=Depends(require_pro)):
    a = db.get(Analysis, analysis_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Análisis no encontrado")
    out_dir = "./generated_pdfs"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"analysis_{analysis_id}.pdf")
    logo = "./static/img/logo.png"
    build_pdf(out_path, a.title, user.name, a.result, logo_path=logo)
    a.pdf_path = out_path
    db.add(a); db.commit()

    month_key = datetime.utcnow().strftime("%Y-%m")
    metric = db.query(DownloadMetric).filter(DownloadMetric.month_key==month_key).first()
    if not metric:
        metric = DownloadMetric(month_key=month_key, count=0)
    metric.count += 1
    db.merge(metric); db.commit()
    return {"pdf_path": out_path}
