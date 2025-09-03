from fastapi.responses import RedirectResponse
from pydantic import BaseModel
import base64

@router.get("/run")
def run_get_redirect():
    return RedirectResponse(url="/dashboard", status_code=302)

class RunPayload(BaseModel):
    title: str | None = "Log Analysis"
    raw_b64: str

@router.post("/run_json")
def run_analysis_json(payload: RunPayload,
                      db: Session = Depends(get_db),
                      user=Depends(get_current_user)):
    try:
        raw_log = base64.b64decode(payload.raw_b64).decode("utf-8", "ignore")
    except Exception:
        raise HTTPException(400, "No se pudo decodificar raw_b64")
    findings = analyze_log(raw_log)
    result = format_result(findings)
    a = Analysis(user_id=user.id, title=payload.title or "Log Analysis",
                 raw_log=raw_log, result=result)
    db.add(a); db.commit(); db.refresh(a)
    return {"id": a.id, "result": a.result}
