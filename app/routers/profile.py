from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import get_current_user, get_password_hash, verify_password
from app import models, schemas

router = APIRouter(prefix="/profile", tags=["profile"])

@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user

@router.post("/change-password")
def change_password(payload: schemas.ChangePasswordIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if not verify_password(payload.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Contraseña actual incorrecta")
    user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"detail": "Contraseña actualizada"}
