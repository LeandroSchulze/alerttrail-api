from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import get_current_user_cookie

router = APIRouter(prefix="/mail", tags=["mail"])

@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, db = Depends(get_db), user = Depends(get_current_user_cookie)):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    html = f"""
    <h1>Casillas de correo</h1>
    <p>Bienvenido, {user.email}</p>
    <form method="post" action="/mail/add">
      <label>Dirección: <input name="email" type="email" required></label>
      <button type="submit">Agregar</button>
    </form>
    <p><a href="/dashboard">Volver</a></p>
    """
    return HTMLResponse(html)

@router.post("/add")
def add_mail_account(email: str = Form(...), db = Depends(get_db), user = Depends(get_current_user_cookie)):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    # Lógica simplificada, deberías guardar la cuenta en la DB
    print(f"[mail] user={user.email} agregó cuenta {email}")
    return HTMLResponse(f"<p>Cuenta {email} agregada.</p><p><a href='/mail'>Volver</a></p>")
