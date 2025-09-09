from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.security import get_current_user, get_password_hash, verify_password

router = APIRouter(prefix="/profile", tags=["profile"])

@router.post("/change-password")
def change_password(old_password: str, new_password: str,
                    db: Session = Depends(get_db),
                    user: models.User = Depends(get_current_user)):
    if not verify_password(old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Clave actual incorrecta")
    user.hashed_password = get_password_hash(new_password)
    db.commit()
    return {"detail": "Password actualizado"}
