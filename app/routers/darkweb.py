# app/routers/darkweb.py
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette import status

from app.database import SessionLocal
from app.models import User
from app.security import get_current_user_cookie
from app.services import darkweb_storage

router = APIRouter(prefix="/darkweb", tags=["darkweb"])


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
def darkweb_dashboard(request: Request, db=Depends(_get_db)) -> HTMLResponse:
    user = _current_user(request, db)
    emails = darkweb_storage.list_emails(user.id)
    exposures = darkweb_storage.list_exposures(user.id)
    ctx = {
        "request": request,
        "user": user,
        "emails": emails,
        "exposures": exposures,
        "page_title": "Dark Web Radar | AlertTrail",
    }
    return request.app.state.templates.TemplateResponse("darkweb.html", ctx)


@router.post("/add-email")
def darkweb_add_email(
    request: Request,
    email: str = Form(...),
    db=Depends(_get_db),
):
    user = _current_user(request, db)
    darkweb_storage.add_email(user.id, email)
    return RedirectResponse("/darkweb", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/remove-email")
def darkweb_remove_email(
    request: Request,
    email: str = Form(...),
    db=Depends(_get_db),
):
    user = _current_user(request, db)
    darkweb_storage.remove_email(user.id, email)
    return RedirectResponse("/darkweb", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/scan")
def darkweb_scan(request: Request, db=Depends(_get_db)):
    user = _current_user(request, db)
    new_count = darkweb_storage.simulate_scan_for_owner(user.id)
    # Podrías guardar este valor en la sesión o mostrar un mensaje en la UI; por ahora solo redirigimos.
    return RedirectResponse("/darkweb", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/mark-seen")
def darkweb_mark_seen(
    request: Request,
    exposure_id: str = Form(...),
    db=Depends(_get_db),
):
    user = _current_user(request, db)
    darkweb_storage.mark_exposure_seen(user.id, exposure_id)
    return RedirectResponse("/darkweb", status_code=status.HTTP_303_SEE_OTHER)
