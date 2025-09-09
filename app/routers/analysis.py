from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from io import BytesIO

from app.services.analysis_service import analyze_log
from app.services.pdf_service import generate_pdf
from app.security import get_current_user

router = APIRouter(prefix="/analysis", tags=["analysis"])

class LogInput(BaseModel):
    log_content: str

@router.post("/generate_pdf")
def generate_pdf_from_log(payload: LogInput, user=Depends(get_current_user)):
    analysis = analyze_log(payload.log_content)
    pdf_bytes = generate_pdf(user_email=user.email, analysis=analysis)
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=analysis.pdf"}
    )
