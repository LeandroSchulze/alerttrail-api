from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.security import get_password_hash

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/create_admin")
async def create_admin(email: str, password: str, name: str = "Admin", db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if user:
        user.password_hash = get_password_hash(password)
        user.name = name
        user.role = "admin"
    else:
        user = User(email=email, name=name, password_hash=get_password_hash(password), role="admin", plan="PRO")
        db.add(user)
    db.commit()
    return {"status": "ok"}
