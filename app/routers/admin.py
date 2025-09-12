from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User
from app.security import get_password_hash, decode_token

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def require_admin(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(401, "No autenticado.")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "Token inválido o expirado.")
    me = db.query(User).filter(User.email == payload.get("sub")).first()
    if not me or me.plan != "pro":
        raise HTTPException(403, "Requiere permisos de administrador.")
    return me

@router.post("/create_admin", tags=["admin"])
def create_admin(
    request: Request,
    email: str = Form(...),
    name: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    u = db.query(User).filter(User.email == email).first()
    if u:
        u.name = name
        u.password_hash = hash_password(password)
        u.plan = "pro"
        db.commit()
    else:
        u = User(email=email, name=name, password_hash=hash_password(password), plan="pro")
        db.add(u); db.commit()
    return RedirectResponse("/dashboard", status_code=303)
