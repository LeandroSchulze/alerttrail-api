# app/routes/orgs.py
from datetime import datetime, timezone, timedelta
import os
import secrets
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Organization, User, OrgInvite
from app.security import get_current_user_cookie # Unificado con tu sistema de cookies

router = APIRouter(prefix="/org", tags=["Organization"])
log = logging.getLogger(__name__)

# =========================
# Seats helpers (Unificado)
# =========================

def max_seats_for_org(org: Organization) -> int:
    """
    Fuente de verdad de asientos. Sincronizado con el sistema de cobros.
    """
    plan = (org.plan or "").upper()

    if plan == "BIZ":
        # Prioridad a la ENV, fallback a los 25 legales del plan
        return int(os.getenv("BIZ_INCLUDED_SEATS", 25))

    if plan == "PRO":
        return 1

    return org.seats_total or 1


def recalc_seats_used(db: Session, org: Organization) -> int:
    """
    Cuenta usuarios activos y actualiza la DB.
    """
    used = (
        db.query(User)
        .filter(User.org_id == org.id, User.is_active == True)
        .count()
    )
    org.seats_used = used
    db.commit()
    return used


# =========================
# Info de mi Organización
# =========================
@router.get("/me")
def get_my_org(
    db: Session = Depends(get_db),
    user_session = Depends(get_current_user_cookie),
):
    # Resolvemos el usuario desde la sesión
    user = db.query(User).get(user_session["sub"])
    
    if not user or not user.org_id:
        raise HTTPException(404, "Usuario sin organización")

    org = db.query(Organization).get(user.org_id)
    if not org:
        raise HTTPException(404, "Organización no encontrada")

    recalc_seats_used(db, org)

    return {
        "id": org.id,
        "name": org.name,
        "plan": org.plan,
        "seats_used": org.seats_used,
        "seats_total": max_seats_for_org(org),
    }


# =========================
# Crear Invitación (Portero de 25 asientos)
# =========================
@router.post("/invite")
def create_invite(
    email: str,
    db: Session = Depends(get_db),
    user_session = Depends(get_current_user_cookie),
):
    user = db.query(User).get(user_session["sub"])
    
    if not user.org_id or not user.is_org_admin:
        raise HTTPException(403, "No tienes permisos de administrador de empresa")

    org = db.query(Organization).get(user.org_id)
    if not org:
        raise HTTPException(404, "Organización no encontrada")

    # Refrescar conteo antes de validar
    recalc_seats_used(db, org)

    # Validación de cupo
    if org.seats_used >= max_seats_for_org(org):
        raise HTTPException(400, f"Has alcanzado el límite de {max_seats_for_org(org)} asientos.")

    token = secrets.token_urlsafe(32)

    invite = OrgInvite(
        org_id=org.id,
        email=email.lower().strip(),
        token=token,
        invited_by_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )

    db.add(invite)
    db.commit()

    log.info(f"Invitación creada para {email} en org {org.id}")
    return {"ok": True, "token": token}


# =========================
# Aceptar Invitación
# =========================
@router.post("/accept-invite")
def accept_invite(
    token: str,
    db: Session = Depends(get_db),
    user_session = Depends(get_current_user_cookie),
):
    invite = db.query(OrgInvite).filter(OrgInvite.token == token).first()
    if not invite:
        raise HTTPException(404, "La invitación no existe")

    if invite.accepted_at:
        raise HTTPException(400, "Esta invitación ya fue utilizada")

    if invite.expires_at and invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "La invitación ha expirado")

    org = db.query(Organization).get(invite.org_id)
    if not org:
        raise HTTPException(404, "La empresa ya no existe")

    recalc_seats_used(db, org)

    if org.seats_used >= max_seats_for_org(org):
        raise HTTPException(400, "La empresa ya no tiene asientos disponibles")

    # Usuario actual que acepta
    user = db.query(User).get(user_session["sub"])

    if not user:
        raise HTTPException(400, "Debes estar registrado para aceptar")

    # Vinculación y herencia de plan
    user.org_id = org.id
    user.plan = org.plan  # Hereda BIZ o el plan de la org
    user.is_org_admin = False

    invite.used_by_user_id = user.id
    invite.accepted_at = datetime.now(timezone.utc)

    db.commit()
    
    # Recalcular al finalizar
    recalc_seats_used(db, org)

    return {"ok": True, "org_name": org.name}
