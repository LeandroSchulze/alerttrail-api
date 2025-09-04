from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..deps import get_current_user, get_db, require_pro
from ..models import Analysis
from ..services.analysis import analyze_log, format_result
from ..services.pdf import build_pdf
import base64

# Router
router = APIRouter(prefix="/analysis", tags=["analysis"])

# --- Redirecciones para GET (si abren /analysis/* en el navegador) ---
@router.get("/", include_in_schema=False)
def analysis_index():
    return RedirectResponse(url="/dashboard", status_code=302)

@router.get("/run", include_in_schema=False)
def run_get_redirect():
    return RedirectResponse(url="/dashboard", status_code=302)

@router.get("/{path:path}", include_in_schema=False)
def analysis_catch_all(path: str):
    return RedirectResponse(url="/dashboard", status_code=302)

# --- POST /analysis/run (form-data). Acepta raw_b64 para evitar bloqueos del WAF ---
@router.post("/run")
def run_analysis(
    title: str = Form("Log Analysis"),
    raw_log: str | None = Form(None),
    raw_b64: str | None = Form(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if (not raw_log) and raw_b64:
        try:
            raw_log = base64.b64decode(raw_b64).decode("utf-8", "ignore")
        except Exception as e:
            raise HTTPException(status_code=400, detail="No se pudo decodificar raw_b64") from e
    if not raw_log:
        raise HTTPException(status_code=400, detail="Falta raw_log o raw_b64")

    findings = analyze_log(raw_log)
    result = format_result(findings)
    a = Analysis(user_id=user.id, title=title, raw_log=raw_log, result=result)
    db.add(a); db.commit(); db.refresh(a)
    return {"id": a.id, "result": a.result}

# --- POST /analysis/run_json (application/json) ---
class RunPayload(BaseModel):
    title: str | None = "Log Analysis"
    raw_b64: str

@router.post("/run_json")
def run_analysis_json(
    payload: RunPayload,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        raw_log = base64.b64decode(payload.raw_b64).decode("utf-8", "ignore")
    except Exception as e:
        raise HTTPException(status_code=400, detail="No se pudo decodificar raw_b64") from e

    findings = analyze_log(raw_log)
    result = format_result(findings)
    a = Analysis(user_id=user.id, title=payload.title or "Log Analysis", raw_log=raw_log, result=result)
    db.add(a); db.commit(); db.refresh(a)
    return {"id": a.id, "result": a.result}

# --- PDF (sólo plan Pro) ---
@router.post("/pdf/{analysis_id}")
def pdf_pro(
    analysis_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_pro),
):
    a = db.get(Analysis, analysis_id)
    if not a or a.user_id != user.id:
        raise HTTPException(status_code=404, detail="Análisis no encontrado")
    path = build_pdf(a, user)
    a.pdf_path = path
    db.add(a); db.commit()
    return {"pdf_path": path}
