# app/routers/training.py
from typing import List

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette import status

from app.database import SessionLocal
from app.models import User
from app.security import get_current_user_cookie
from app.services import training_storage

router = APIRouter(prefix="/training", tags=["training"])

PHISHING_TEMPLATES = [
    {"id": "password_reset", "name": "Reset de contraseña falsa"},
    {"id": "package", "name": "Paquete retenido (envío)"},
    {"id": "invoice", "name": "Factura inesperada"},
]


def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _current_user(request: Request, db) -> User:
    payload = get_current_user_cookie(request)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise RedirectResponse("/auth/login", status_code=status.HTTP_302_FOUND)
    return user


@router.get("", response_class=HTMLResponse)
def training_home(request: Request, db=Depends(_get_db)) -> HTMLResponse:
    user = _current_user(request, db)
    recipients = training_storage.list_recipients(user.id)
    campaigns = training_storage.list_campaigns(user.id)
    ctx = {
        "request": request,
        "user": user,
        "recipients": recipients,
        "campaigns": campaigns,
        "templates": PHISHING_TEMPLATES,
        "page_title": "Phishing Training | AlertTrail",
    }
    return request.app.state.templates.TemplateResponse("training.html", ctx)


@router.post("/recipients/add")
def training_add_recipient(
    request: Request,
    email: str = Form(...),
    name: str = Form(""),
    db=Depends(_get_db),
):
    user = _current_user(request, db)
    training_storage.add_recipient(user.id, email, name)
    return RedirectResponse("/training", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/recipients/delete")
def training_delete_recipient(
    request: Request,
    email: str = Form(...),
    db=Depends(_get_db),
):
    user = _current_user(request, db)
    training_storage.delete_recipient(user.id, email)
    return RedirectResponse("/training", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/campaigns/create")
def training_create_campaign(
    request: Request,
    name: str = Form(""),
    template_id: str = Form(...),
    db=Depends(_get_db),
):
    user = _current_user(request, db)
    recipients = training_storage.list_recipients(user.id)
    recipient_emails: List[str] = [r.get("email") for r in recipients if r.get("email")]
    training_storage.create_campaign(user.id, name, template_id, recipient_emails)
    return RedirectResponse("/training", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/campaigns/mark-sent")
def training_mark_sent(
    request: Request,
    campaign_id: str = Form(...),
    db=Depends(_get_db),
):
    """
    Por ahora solo marcamos la campaña como 'sent' de forma simulada.
    Más adelante se puede enganchar un envío real de correos.
    """
    user = _current_user(request, db)
    training_storage.mark_campaign_sent(user.id, campaign_id)
    return RedirectResponse("/training", status_code=status.HTTP_303_SEE_OTHER)
