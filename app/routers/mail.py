from fastapi import APIRouter
router = APIRouter()

@router.get("/scan")
def scan_mail():
    # TODO: lógica real
    return {"status": "scanned"}
