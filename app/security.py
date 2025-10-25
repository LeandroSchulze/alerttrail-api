# app/routers/auth.py (fragmento del POST /auth/login/web)
from fastapi import APIRouter, Depends, Request, Form
from starlette.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.security import verify_and_rehash, create_access_token, issue_access_cookie

@router.post("/auth/login/web")
def login_web(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).one_or_none()
    if not user:
        return RedirectResponse(url="/auth/login?error=1", status_code=303)

    # toma cualquiera de los 2 campos
    hp = getattr(user, "hashed_password", None) or getattr(user, "password_hash", None) or ""
    ok, new_hash = verify_and_rehash(password, hp)
    if not ok:
        return RedirectResponse(url="/auth/login?error=1", status_code=303)

    # rehash: guarda en ambos campos para evitar futuros desajustes
    if new_hash:
        user.hashed_password = new_hash
        user.password_hash = new_hash
        db.add(user); db.commit()

    token = create_access_token({"sub": str(user.id), "email": user.email})
    resp = RedirectResponse(url="/dashboard", status_code=303)
    issue_access_cookie(resp, token)
    return resp
