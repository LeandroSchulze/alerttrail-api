from fastapi import APIRouter

router = APIRouter(prefix="/settings", tags=["settings"])

@router.get("/health")
def health():
    return {"status": "ok"}
