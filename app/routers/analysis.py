from fastapi import APIRouter
router = APIRouter()

@router.get("/generate_pdf")
def generate_pdf():
    # TODO: lógica real de PDF
    return {"url": "/reports/demo.pdf"}
