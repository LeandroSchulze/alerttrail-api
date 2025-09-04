from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..deps import get_current_user, get_db, require_pro
from ..models import Analysis
from ..services.analysis import analyze_log, format_result
from ..services.pdf import build_pdf
import base64

# ✅ primero creamos el router
router = APIRouter(prefix="/analysis", tags=["analysis"])

# --- GET /analysis/run -> redirige al dashboard (evita abrirlo directo y ver 403/GET) ---
@router.get("/run")
def run_get_redirect():
    return RedirectResponse(url="/dashboard", status_code=302)

# --- POST /analysis/run (form) acepta raw_b64 para evitar WAF ---
@router.post("/run")
def run_analysis(
    raw_log: str | None = Form(None),
    raw_b64: str | None = Form(None),
    title: str = Form("Log Analysis"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
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

# --- POST /analysis/run_json (JSON) { "title": "...", "raw_b64": "..." } ---
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
    except Exception:
        raise HTTPException(status_code=400, detail="No se pudo decodificar raw_b64")

    findings = analyze_log(raw_log)
    result = format_result(findings)
    a = Analysis(user_id=user.id, title=payload.title or "Log Analysis", raw_log=raw_log, result=result)
    db.add(a); db.commit(); db.refresh(a)
    return {"id": a.id, "result": a.result}

# --- PDF Pro ---
@router.post("/pdf/{analysis_id}")
def pdf_pro(analysis_id: int, db: Session = Depends(get_db), user=Depends(require_pro)):
    a = db.get(Analysis, analysis_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Análisis no encontrado")
    path = build_pdf(a, user)
    a.pdf_path = path
    db.add(a); db.commit()
    return {"pdf_path": path}
