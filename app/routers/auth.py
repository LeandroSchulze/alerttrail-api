from fastapi import APIRouter
router = APIRouter()

@router.get("/login")
def login():
    return {"ok": True, "msg": "login OK (demo)"}
