# app/routes/orgs.py
from datetime import datetime, timedelta
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Organization, User, OrgInvite
from app.auth import get_current_user

router = APIRouter(prefix="/org", tags=["Organization"])


# =========================
# Seats helpers (ENV-based)
# =========================

def max_seats_for_org(org: Organization) -> int:
    """
    Fuente de verdad de asientos.
    Usa ENV según plan, con fallback a org.seats_total.
    """
    plan = (org.plan or "").upper()

    if plan == "BIZ":
        return int(os.getenv("BIZ_INCLUDED_SEATS", org.seats_total or 25))

    # futuros planes
    if plan == "PRO":
        return int(os.getenv("PRO_INCLUDED_SEATS", org.seats_total or 1))

    return org.seats_total or 1


def recalc_seats_used(db: Session, org: Organization) -> int:
    used = (
        db.query(User)
        .filter(User.org_id == org.id, User.is_active == True)
        .count()
    )
    org.seats_used = used
    db.commit()
    return used


# =========================
# Get org info
# =========================
@router.get("/me")
def get_my_org(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.org_id:
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
# Create invite
# =========================
@router.post("/invite")
def create_invite(
    email: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.org_id or not user.is_org_admin:
        raise HTTPException(403, "No autorizado")

    org = db.query(Organization).get(user.org_id)
    if not org:
        raise HTTPException(404, "Organización no encontrada")

    recalc_seats_used(db, org)

    if org.seats_used >= max_seats_for_org(org):
        raise HTTPException(400, "No hay asientos disponibles")

    token = secrets.token_urlsafe(32)

    invite = OrgInvite(
        org_id=org.id,
        email=email.lower(),
        token=token,
        invited_by_id=user.id,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )

    db.add(invite)
    db.commit()

    return {"ok": True, "token": token}


# =========================
# Accept invite
# =========================
@router.post("/accept-invite")
def accept_invite(
    token: str,
    db: Session = Depends(get_db),
):
    invite = db.query(OrgInvite).filter(OrgInvite.token == token).first()
    if not invite:
        raise HTTPException(404, "Invitación inválida")

    if invite.accepted_at:
        raise HTTPException(400, "Invitación ya usada")

    if invite.expires_at and invite.expires_at < datetime.utcnow():
        raise HTTPException(400, "Invitación expirada")

    org = db.query(Organization).get(invite.org_id)
    if not org:
        raise HTTPException(404, "Organización no encontrada")

    recalc_seats_used(db, org)

    if org.seats_used >= max_seats_for_org(org):
        raise HTTPException(400, "No hay asientos disponibles")

    user = (
        db.query(User)
        .filter(User.email == invite.email.lower())
        .first()
    )

    if not user:
        raise HTTPException(400, "El usuario debe registrarse primero")

    user.org_id = org.id
    user.plan = org.plan
    user.is_org_admin = False

    invite.used_by_user_id = user.id
    invite.accepted_at = datetime.utcnow()

    recalc_seats_used(db, org)
    db.commit()

    return {"ok": True}
