# app/routers/orgs.py
"""
Gestión de organizaciones (plan Empresas/BIZ): asientos e invitaciones.

Endpoints principales:
- GET  /org/me                         → resumen de la organización del usuario logueado
- GET  /org/invites                    → (admin org) listar invitaciones
- POST /org/invites                    → (admin org) crear invitación (opcional email)
- DELETE /org/invites/{invite_id}      → (admin org) revocar/eliminar invitación
- GET  /org/accept-invite              → página HTML para aceptar invitación (token)
- POST /org/accept-invite              → alta de usuario consumiendo asiento
- GET  /org/users                      → (admin org) listar usuarios de la organización
- POST /org/users/{user_id}/remove     → (admin org) remover usuario de la organización
- POST /org/seats/increment            → (admin org) sumar asientos totales (p.ej. +N)

Requisitos:
- Modelos Organization, OrgInvite, User agregados en app/models.py (ya los tenés).
- init_db.py actualizado para crear/alterar tablas/columnas (ya lo tenés).
- Seguridad: get_current_user_cookie para obtener el usuario logueado.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app import models

# Dependencias de seguridad (con fallback)
try:
    from app.security import get_current_user_cookie, get_password_hash
except Exception:  # fallback si tenés helpers en otro módulo
    from app.utils.security import get_current_user_cookie, get_password_hash  # type: ignore

router = APIRouter(prefix="/org", tags=["org"])


# --------------------------
# Helpers
# --------------------------
def _require_logged_user(user: models.User):
    if not user or not getattr(user, "id", None):
        raise HTTPException(status_code=401, detail="No autenticado")

def _require_org_admin(user: models.User):
    _require_logged_user(user)
    if not getattr(user, "org_id", None) or not bool(getattr(user, "is_org_admin", False)):
        raise HTTPException(status_code=403, detail="Solo administradores de organización")

def _norm_email(e: str) -> str:
    return (e or "").strip().lower()

def _recalc_seats_used(db: Session, org: models.Organization) -> int:
    used = db.query(models.User).filter(
        models.User.org_id == org.id,
        models.User.is_active == True,   # noqa: E712
    ).count()
    org.seats_used = used
    db.add(org)
    db.commit()
    return used


# --------------------------
# Resumen de mi organización
# --------------------------
@router.get("/me")
def my_org_summary(user=Depends(get_current_user_cookie), db: Session = Depends(get_db)):
    if not user or not user.org_id:
        return {"org": None, "is_org_admin": False}

    org = db.query(models.Organization).get(user.org_id)
    if not org:
        return {"org": None, "is_org_admin": False}

    # Traemos conteo actualizado (no siempre necesario, pero útil)
    used = _recalc_seats_used(db, org)

    return {
        "org": {
            "id": org.id,
            "name": org.name,
            "seats_total": org.seats_total,
            "seats_used": used,
            "billing_id": org.billing_id,
        },
        "is_org_admin": bool(user.is_org_admin),
    }


# --------------------------
# Invitaciones (admin org)
# --------------------------
@router.get("/invites")
def list_invites(user=Depends(get_current_user_cookie), db: Session = Depends(get_db)):
    _require_org_admin(user)
    invites = db.query(models.OrgInvite).filter(
        models.OrgInvite.org_id == user.org_id
    ).order_by(models.OrgInvite.created_at.desc()).all()

    out = []
    for inv in invites:
        out.append({
            "id": inv.id,
            "email": inv.email,
            "token": inv.token,
            "used": inv.used,
            "used_by_user_id": inv.used_by_user_id,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "invite_link": f"/org/accept-invite?token={inv.token}",
        })
    return {"invites": out}


@router.post("/invites")
async def create_invite(
    request: Request,
    email: Optional[str] = Form(None),
    user=Depends(get_current_user_cookie),
    db: Session = Depends(get_db),
):
    """
    Crea una invitación para sumar un usuario a la organización.
    Si no se especifica email, el link es genérico y se puede compartir.
    A criterio de negocio: bloqueamos creación de invites si no hay asientos libres.
    """
    _require_org_admin(user)
    org = db.query(models.Organization).get(user.org_id)
    if not org:
        raise HTTPException(404, "Organización no encontrada")

    # Soft-cap: si no hay asientos libres, no crear invitación
    _recalc_seats_used(db, org)
    if org.seats_used >= org.seats_total:
        raise HTTPException(400, "No hay asientos disponibles")

    token = uuid.uuid4().hex
    inv = models.OrgInvite(org_id=org.id, token=token, email=_norm_email(email) if email else None)
    db.add(inv)
    db.commit()

    link = f"/org/accept-invite?token={token}"
    return {"ok": True, "invite_link": link, "token": token}


@router.delete("/invites/{invite_id}")
def delete_invite(invite_id: int, user=Depends(get_current_user_cookie), db: Session = Depends(get_db)):
    _require_org_admin(user)
    inv = db.query(models.OrgInvite).filter(
        models.OrgInvite.id == invite_id,
        models.OrgInvite.org_id == user.org_id,
    ).first()
    if not inv:
        raise HTTPException(404, "Invitación no encontrada")
    db.delete(inv)
    db.commit()
    return {"ok": True}


# --------------------------
# Aceptar invitación
# --------------------------
@router.get("/accept-invite", response_class=HTMLResponse)
def accept_invite_page(token: str, request: Request, db: Session = Depends(get_db)):
    inv = db.query(models.OrgInvite).filter_by(token=token, used=False).first()
    if not inv:
        return HTMLResponse("<h3>Invitación inválida o usada</h3>", status_code=400)

    org = db.query(models.Organization).get(inv.org_id)
    if not org:
        return HTMLResponse("<h3>Organización no encontrada</h3>", status_code=400)

    # Verificación simple de asientos
    if _recalc_seats_used(db, org) >= org.seats_total:
        return HTMLResponse("<h3>No hay asientos disponibles. Contactá al administrador.</h3>", status_code=400)

    # HTML muy simple para no depender de templates (podés migrarlo a Jinja2 luego)
    return HTMLResponse(f"""
<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Aceptar invitación — {org.name}</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  body{{font-family:system-ui,Segoe UI,Roboto,Arial;max-width:520px;margin:40px auto;padding:0 12px;color:#0f172a}}
  .card{{border:1px solid #e5e7eb;border-radius:12px;padding:16px;background:#fff}}
  label{{display:block;margin:10px 0 4px}}
  input{{width:100%;padding:10px;border:1px solid #e5e7eb;border-radius:8px}}
  button{{margin-top:12px;padding:10px 14px;border:0;border-radius:10px;background:#2563eb;color:#fff;font-weight:700;cursor:pointer}}
  .muted{{color:#475569}}
</style>
</head><body>
  <h2>Unite a <strong>{org.name}</strong></h2>
  <p class="muted">Completá tus datos para crear tu cuenta y ocupar 1 asiento.</p>
  <div class="card">
  <form method="POST" action="/org/accept-invite">
    <input type="hidden" name="token" value="{token}">
    <label>Nombre</label>
    <input name="name" required>
    <label>Email</label>
    <input name="email" value="{inv.email or ''}" required>
    <label>Contraseña</label>
    <input name="password" type="password" required>
    <button>Crear cuenta</button>
  </form>
  </div>
  <p class="muted" style="margin-top:10px">¿Ya tenés cuenta? Pedile al admin que te asocie desde el panel.</p>
</body></html>
""")


@router.post("/accept-invite")
def accept_invite(
    token: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    inv = db.query(models.OrgInvite).filter_by(token=token, used=False).first()
    if not inv:
        raise HTTPException(400, "Invitación inválida o usada")

    org = db.query(models.Organization).get(inv.org_id)
    if not org:
        raise HTTPException(400, "Organización no encontrada")

    # Verificar asientos antes de crear
    used = _recalc_seats_used(db, org)
    if used >= org.seats_total:
        raise HTTPException(400, "No hay asientos disponibles")

    email_n = _norm_email(email)
    existing = db.query(models.User).filter(func.lower(models.User.email) == email_n).first()
    if existing:
        raise HTTPException(400, "El email ya está registrado. Iniciá sesión o usá otro email.")

    # Crear usuario
    u = models.User(
        name=name.strip(),
        email=email_n,
        password_hash=get_password_hash(password),
        plan="BIZ",            # opcional: o mantener FREE/PRO y gobernar por org
        role="user",
        is_admin=False,
        is_superuser=False,
        is_active=True,
        org_id=org.id,
        # is_org_admin=False por defecto
    )
    db.add(u)
    # Marcar invitación usada
    inv.used = True
    # flush para obtener u.id
    db.flush()
    inv.used_by_user_id = u.id

    # Recontar asientos y persistir
    _recalc_seats_used(db, org)

    db.commit()
    # Redirigir a login (ajustá si tu ruta es distinta)
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)


# --------------------------
# Usuarios de la organización (admin)
# --------------------------
@router.get("/users")
def list_org_users(user=Depends(get_current_user_cookie), db: Session = Depends(get_db)):
    _require_org_admin(user)
    users = db.query(models.User).filter(models.User.org_id == user.org_id).order_by(models.User.created_at.asc()).all()
    out = []
    for u in users:
        out.append({
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "is_active": u.is_active,
            "is_org_admin": bool(getattr(u, "is_org_admin", False)),
            "plan": getattr(u, "plan", None),
            "created_at": u.created_at.isoformat() if u.created_at else None,
        })
    return {"users": out}


@router.post("/users/{user_id}/remove")
def remove_user_from_org(user_id: int, user=Depends(get_current_user_cookie), db: Session = Depends(get_db)):
    """
    Remueve un usuario de la organización y libera el asiento.
    No borra el usuario; solo le quita org_id e is_org_admin.
    """
    _require_org_admin(user)
    target = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.org_id == user.org_id
    ).first()
    if not target:
        raise HTTPException(404, "Usuario no encontrado en tu organización")

    if target.id == user.id and target.is_org_admin:
        raise HTTPException(400, "No podés removerte a vos mismo como admin desde aquí")

    target.org_id = None
    target.is_org_admin = False
    db.add(target)

    org = db.query(models.Organization).get(user.org_id)
    _recalc_seats_used(db, org)
    db.commit()
    return {"ok": True}


# --------------------------
# Ajustar asientos (admin) - útil para pruebas/backoffice
# --------------------------
@router.post("/seats/increment")
def increment_seats(
    n: int = Form(..., gt=1),   # cantidad a sumar
    user=Depends(get_current_user_cookie),
    db: Session = Depends(get_db),
):
    _require_org_admin(user)
    org = db.query(models.Organization).get(user.org_id)
    if not org:
        raise HTTPException(404, "Organización no encontrada")
    org.seats_total = int(org.seats_total or 0) + int(n)
    _recalc_seats_used(db, org)
    db.commit()
    return {"ok": True, "seats_total": org.seats_total, "seats_used": org.seats_used}
