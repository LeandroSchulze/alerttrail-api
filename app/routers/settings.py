from fastapi import APIRouter
router = APIRouter(prefix="/settings", tags=["settings"])

@router.get("")
def get_settings():
    return {"ok": True}
