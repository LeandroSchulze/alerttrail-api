# app/routers/mail.py
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import get_current_user_cookie
from app.models import User

router = APIRouter(prefix="/mail", tags=["mail"])

@router.get("/", response_class=HTMLResponse, response_model=None)
def mail_index(request: Request, db: Session = Depends(get_db)):
    # payload desde cookie + lookup del usuario real
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    # Mantengo el HTML original (no rompo nada) y solo agrego el link a la pantalla IMAP.
    html = f"""
    <h1>Casillas de correo</h1>
    <p>Bienvenido, {user.email}</p>
    <form method="post" action="/mail/add">
      <label>Dirección: <input name="email" type="email" required></label>
      <button type="submit">Agregar</button>
    </form>
    <p><a href="/mail/connect">Vincular casilla (IMAP)</a></p>
    <p><a href="/dashboard">Volver</a></p>
    """
    return HTMLResponse(html)

@router.get("/connect", response_class=HTMLResponse, include_in_schema=False)
def mail_connect_form(request: Request, db: Session = Depends(get_db)):
    """
    Render del formulario IMAP (usa el template que me pasaste).
    """
    # Si necesitás el usuario por seguridad/estado, se puede verificar:
    _ = get_current_user_cookie(request)
    tpl = request.app.state.templates
    ctx = {"request": request, "ok": False, "error": None, "email_addr": ""}
    return tpl.TemplateResponse("mail_connect.html", ctx)

@router.post("/connect", response_class=HTMLResponse, include_in_schema=False)
def mail_connect_submit(
    request: Request,
    email_addr: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    imap_server: str = Form("imap.gmail.com"),
    imap_port: int = Form(993),
    use_ssl: bool = Form(True),
    db: Session = Depends(get_db),
):
    """
    POST del formulario IMAP. Acá hoy solo validamos y mostramos OK.
    (No toco storage/DB para no romper nada que ya tengas).
    """
    try:
        _ = get_current_user_cookie(request)
    except Exception:
        raise HTTPException(status_code=401, detail="No autenticado")

    # Validación mínima
    if not email_addr or "@" not in email_addr:
        error = "Email inválido."
    elif not username:
        error = "Falta el usuario IMAP."
    elif not password:
        error = "Falta la contraseña o App Password."
    else:
        error = None

    tpl = request.app.state.templates
    if error:
        return tpl.TemplateResponse(
            "mail_connect.html",
            {"request": request, "ok": False, "error": error, "email_addr": email_addr},
        )

    # En tu implementación real, acá guardarías las credenciales cifradas
    # y programarías el primer escaneo, etc.
    print(f"[mail] vinculado IMAP email={email_addr} user={username} host={imap_server}:{imap_port} ssl={use_ssl}")

    return tpl.TemplateResponse(
        "mail_connect.html",
        {"request": request, "ok": True, "error": None, "email_addr": email_addr},
    )

@router.post("/add", response_model=None)
def add_mail_account(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    # Lógica simplificada, deberías guardar la cuenta en la DB
    print(f"[mail] user={user.email} agregó cuenta {email}")
    return HTMLResponse(f"<p>Cuenta {email} agregada.</p><p><a href='/mail'>Volver</a></p>")
