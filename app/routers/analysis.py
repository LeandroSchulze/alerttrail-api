from fastapi import APIRouter, Depends
from pydantic import BaseModel
from datetime import datetime
from io import BytesIO
import os

from app.services.analysis_service import analyze_log
from app.services.pdf_service import generate_pdf
from app.security import get_current_user

router = APIRouter(prefix="/analysis", tags=["analysis"])

REPORTS_DIR = "/var/data/reports"
os.makedirs(REPORTS_DIR, exist_ok=True)

class LogInput(BaseModel):
    log_content: str

@router.post("/generate_pdf")
def generate_pdf_and_return_url(payload: LogInput, user=Depends(get_current_user)):
    # 1) Analizar
    analysis = analyze_log(payload.log_content)
    # 2) Generar bytes del PDF
    pdf_bytes = generate_pdf(user_email=user.email, analysis=analysis)
    # 3) Guardar con nombre único
    fname = f"analysis_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    fpath = os.path.join(REPORTS_DIR, fname)
    with open(fpath, "wb") as f:
        f.write(pdf_bytes)
    # 4) Devolver URL pública que el front ya espera
    return {"url": f"/reports/{fname}"}
