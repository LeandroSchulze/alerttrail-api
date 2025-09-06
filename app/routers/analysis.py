from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.security import get_current_user
from app.config import get_settings
from app import models, schemas
from app.services.analysis_service import analyze_log
from app.services.pdf_service import generate_pdf

router = APIRouter(prefix="/analysis", tags=["analysis"])
settings = get_settings()

def _today_key() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")

def _check_free_limit(db: Session, user: models.User):
    if user.plan == "PRO":
        return
    key = _today_key()
    usage = db.query(models.UsageCounter).filter_by(user_id=user.id, date_key=key).first()
    if usage and usage.count >= settings.FREE_DAILY_LIMIT:
        raise HTTPException(status_code=402, detail="Límite diario del plan gratuito alcanzado")

def _increment_usage(db: Session, user: models.User):
    key = _today_key()
    usage = db.query(models.UsageCounter).filter_by(user_id=user.id, date_key=key).first()
    if not usage:
        usage = models.UsageCounter(user_id=user.id, date_key=key, count=0)
        db.add(usage)
    usage.count += 1
    db.commit()

@router.post("/run", response_model=schemas.AnalysisOut)
def run_analysis(payload: schemas.AnalysisIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _check_free_limit(db, user)
    result = analyze_log(payload.raw_log, use_ai=(user.plan == "PRO"))

    report_data = {
        "Usuario": user.email,
        "Fuente": payload.source_name or "log.txt",
        "Resumen": result["summary"],
        "Riesgo": result["score"],
        "Fecha": datetime.utcnow().isoformat() + "Z",
    }
    pdf_path = None
    if user.plan == "PRO":
        pdf_path = generate_pdf(report_data, filename_prefix=f"analysis_{user.id}")

    analysis = models.Analysis(
        user_id=user.id,
        source_name=payload.source_name,
        raw_log=payload.raw_log,
        result_summary=result["summary"],
        score_risk=result["score"],
        pdf_path=pdf_path,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    _increment_usage(db, user)
    return analysis
