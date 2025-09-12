# app/routers/admin.py
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_password_hash, decode_token

router = APIRouter()

def require_admin(request: Request, db: Session) -> User:
    """
    Verifica que exista cookie de sesión válida y que el usuario sea admin.
    Por ahora consideramos admin a quien tenga plan == "pro".
    """
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado.")

    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido o expirado.")

    me = db.query(User).filter(User.email == payload.get("sub")).first()
    if not me:
        raise HTTPException(status_code=401, detail="No autenticado.")

    if me.plan != "pro":
        raise HTTPException(status_code=403, detail="Requiere permisos de administrador.")

    return me

@router.post("/create_admin", tags=["admin"])
def create_admin(
    request: Request,
    email: str = Form(...),
    name: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Crea o actualiza un usuario con plan PRO (rol admin).
    Protegido: requiere sesión de admin (cookie HTTPOnly).
    """
    require_admin(request, db)

    user = db.query(User).filter(User.email == email).first()
    if user:
        user.name = name
        user.password_hash = get_password_hash(password)
        user.plan = "pro"
        db.commit()
    else:
        user = User(
            email=email,
            name=name,
            password_hash=get_password_hash(password),
            plan="pro",
        )
        db.add(user)
        db.commit()

    # Redirige de vuelta al dashboard
    return RedirectResponse("/dashboard", status_code=303)
