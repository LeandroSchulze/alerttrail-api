from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.security import get_current_user
from app.services.pdf_service import generate_pdf

router = APIRouter(prefix="/analysis", tags=["analysis"])

@router.post("/run")
def run_simple_analysis(text: str = "Ejemplo de análisis",
                        db: Session = Depends(get_db),
                        user: models.User = Depends(get_current_user)):
    pdf_path = generate_pdf({"Usuario": user.email, "Texto": text}, "analysis")
    a = models.Analysis(user_email=user.email, input_text=text, pdf_path=pdf_path)
    db.add(a); db.commit()
    return {"pdf_path": pdf_path}
