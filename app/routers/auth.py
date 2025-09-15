# app/routers/auth.py
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    Form,
    status,
    Request,
)
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os

from app.database import get_db
from app import models
from app.schemas import RegisterIn, LoginIn, UserOut  # si no usás UserOut, no pasa nada
from app.security import (
    get_password_hash,
    verify_password,
    create_access_token_from_sub,  # alias a create_access_token
    issue_access_cookie,
    clear_access_cookie,
    COOKIE_NAME,
    get_current_user_cookie,       # requiere (request, db)
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Templates (usa app/templates por defecto)
APP_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# --------- Helpers internos ----------
def _get_user_password_hash(u: models.User) -> str:
    """Devuelve el hash de contraseña sin importar el nombre del campo."""
    return getattr(u, "password_hash", None) or getattr(u, "hashed_password", "")


# --------- Vistas ----------
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    """Formulario de login. Si ya está logueado, va al dashboard."""
    user = get_current_user_cookie(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
async def login(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Login que acepta JSON (application/json) o Form (application/x-www-form-urlencoded).
    Devuelve token y setea cookie HTTPOnly.
    """
    ctype = (request.headers.get("content-type") or "").lower()
    if ctype.startswith("application/json"):
        body = await request.json()
        email = (body or {}).get("email")
        password = (body or {}).get("password")
    else:
        form = await request.form()
        email = form.get("email")
        password = form.get("password")

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, _get_user_password_hash(user)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")

    token = create_access_token_from_sub(user.email)
    issue_access_cookie(response, token)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/login/web", include_in_schema=False)
def login_web(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    """Login desde formulario HTML. Redirige a /dashboard con cookie seteada."""
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, _get_user_password_hash(user)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")

    token = create_access_token_from_sub(user.email)
    resp = Response(status_code=303)
    resp.headers["Location"] = "/dashboard"
    issue_access_cookie(resp, token)
    return resp


@router.post("/logout")
def logout_post():
    """Logout por POST: borra cookie y redirige a /auth/login."""
    resp = RedirectResponse(url="/auth/login", status_code=302)
    clear_access_cookie(resp)
    return resp


@router.get("/logout")
def logout_get():
    """Logout por GET (comodín)."""
    resp = RedirectResponse(url="/auth/login", status_code=302)
    clear_access_cookie(resp)
    return resp


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    """Devuelve el usuario autenticado leyendo el JWT de la cookie."""
    current = get_current_user_cookie(request, db)
    if not current:
        raise HTTPException(status_code=401, detail="No autenticado")
    return {
        "name": current.name,
        "email": current.email,
        "plan": getattr(current, "plan", "FREE"),
    }


@router.post("/register", response_model=UserOut)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    """Crea un usuario FREE."""
    exists = db.query(models.User).filter(models.User.email == data.email).first()
    if exists:
        raise HTTPException(status_code=400, detail="El email ya está registrado.")

    user = models.User(
        email=data.email,
        name=data.name,
        plan="FREE",
    )
    # Guardamos la contraseña en el/los campo(s) presentes
    pwd = get_password_hash(data.password)
    if hasattr(user, "password_hash"):
        user.password_hash = pwd
    if hasattr(user, "hashed_password"):
        user.hashed_password = pwd

    db.add(user)
    db.commit()
    db.refresh(user)
    return user
