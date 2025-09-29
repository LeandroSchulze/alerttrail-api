# app/routers/orgs.py
"""
Gestión de organizaciones (plan Empresas/BIZ): asientos e invitaciones.

Endpoints principales:
- GET  /org/admin                     → panel HTML para admins de organización
- GET  /org/me                        → resumen JSON de la organización del usuario
- GET  /org/invites                   → (admin org) listar invitaciones
- POST /org/invites                   → (admin org) crear invitación (opcional email)
- POST /org/invites/{invite_id}/delete→ (admin org) eliminar invitación (helper HTML)
- DELETE /org/invites/{invite_id}     → (admin org) eliminar invitación (API)
- GET  /org/accept-invite             → página HTML para aceptar invitación (token)
- POST /org/accept-invite             → alta de usuario consumiendo asiento
- GET  /org/users                     → (admin org) listar usuarios de la organización (JSON)
- POST /org/users/{user_id}/remove    → (admin org) remover usuario de la organización
- POST /org/seats/increment           → (admin org) sumar asientos totales (p.ej. +N)

Requisitos:
- Modelos Organization, OrgInvite, User en app/models.py
- init_db.py actualizado para crear/alterar tablas/columnas
- Seguridad: get_current_user_cookie para obtener el usuario logueado
"""

import uuid, html
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
# Panel HTML de administración de la organización
# --------------------------
@router.get("/admin", response_class=HTMLResponse)
def org_admin_panel(user=Depends(get_current_user_cookie), db: Session = Depends(get_db)):
    _require_org_admin(user)
    org = db.query(models.Organization).get(user.org_id)
    if not org:
        raise HTTPException(404, "Organización no encontrada")

    used = _recalc_seats_used(db, org)

    invites = db.query(models.OrgInvite)\
        .filter(models.OrgInvite.org_id == org.id)\
        .order_by(models.OrgInvite.created_at.desc())\
        .all()

    users = db.query(models.User)\
        .filter(models.User.org_id == org.id)\
        .order_by(models.User.created_at.asc())\
        .all()

    # Render simple inline (podés migrarlo a Jinja2 cuando quieras)
    esc = html.escape
    rows_invites = "".join(
        f"<tr>"
        f"<td>{esc(inv.email or '—')}</td>"
        f"<td><code>{esc(inv.token)}</code></td>"
        f"<td>{'Sí' if inv.used else 'No'}</td>"
        f"<td>{esc(inv.created_at.isoformat() if inv.created_at else '')}</td>"
        f"<td><a href='/org/accept-invite?token={esc(inv.token)}' target='_blank'>Abrir link</a></td>"
        f"<td>"
        f"<form method='POST' action='/org/invites/{inv.id}/delete' onsubmit=\"return confirm('¿Eliminar invitación?');\">"
        f"<button class='danger'>Eliminar</button>"
        f"</form>"
        f"</td>"
        f"</tr>"
        for inv in invites
    ) or "<tr><td colspan='6' class='muted'>No hay invitaciones aún</td></tr>"

    rows_users = "".join(
        f"<tr>"
        f"<td>{esc(u.name or '')}</td>"
        f"<td>{esc(u.email or '')}</td>"
        f"<td>{'Sí' if getattr(u, 'is_org_admin', False) else 'No'}</td>"
        f"<td>{'Sí' if getattr(u, 'is_active', True) else 'No'}</td>"
        f"<td>{esc(u.created_at.isoformat() if u.created_at else '')}</td>"
        f"<td>"
        + ("" if (u.id == user.id and getattr(u, 'is_org_admin', False)) else
           f"<form method='POST' action='/org/users/{u.id}/remove' onsubmit=\"return confirm('¿Remover usuario de la organización?');\">"
           f"<button>Remover</button></form>")
        + f"</td>"
        f"</tr>"
        for u in users
    ) or "<tr><td colspan='6' class='muted'>No hay usuarios aún</td></tr>"

    html_page = f"""
<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Administración de organización — {esc(org.name)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root {{
    --bg:#f7fafc; --panel:#ffffff; --text:#0f172a; --muted:#475569; --line:#e5e7eb; --brand:#2563eb;
  }}
  body{{font-family:system-ui,Segoe UI,Roboto,Arial;margin:0;background:var(--bg);color:var(--text)}}
  .container{{max-width:1100px;margin:0 auto;padding:20px}}
  h1{{margin:0 0 10px}}
  .muted{{color:var(--muted)}}
  .grid{{display:grid;gap:16px;margin-top:16px}}
  @media(min-width:980px){{.grid{{grid-template-columns:1fr 1fr}}}}
  .card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px}}
  .card h3{{margin:0 0 8px}}
  input[type="text"], input[type="number"], input[type="email"]{{width:100%;padding:10px;border:1px solid var(--line);border-radius:10px}}
  button{{padding:10px 14px;border:0;border-radius:10px;background:var(--brand);color:#fff;font-weight:700;cursor:pointer}}
  button.danger{{background:#ef4444}}
  table{{width:100%;border-collapse:collapse}}
  th,td{{text-align:left;padding:10px;border-bottom:1px solid var(--line);vertical-align:top}}
  code{{background:#f1f5f9;padding:2px 6px;border-radius:6px}}
  .pill{{display:inline-block;background:#eef2ff;color:#1e3a8a;border:1px solid #dbeafe;padding:6px 10px;border-radius:999px;font-weight:600}}
  .row{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
  a{{color:#0b5dd7;text-decoration:none}}
</style>
</head><body>
  <div class="container">
    <div class="row" style="justify-content:space-between">
      <h1>Organización: {esc(org.name)}</h1>
      <a href="/dashboard" class="pill">← Volver al dashboard</a>
    </div>
    <p class="muted">Asientos: <strong>{used}</strong> / <strong>{org.seats_total}</strong></p>

    <div class="grid">
      <section class="card">
        <h3>Invitar usuario</h3>
        <p class="muted">Podés dejar el email vacío para generar un link genérico.</p>
        <form method="POST" action="/org/invites">
          <label>Email (opcional)</label>
          <input type="email" name="email" placeholder="persona@empresa.com" />
          <div style="margin-top:10px"><button>Crear invitación</button></div>
        </form>
      </section>

      <section class="card">
        <h3>Sumar asientos</h3>
        <form method="POST" action="/org/seats/increment" class="row">
          <div style="flex:1;min-width:120px">
            <label>Cantidad a sumar</label>
            <input type="number" name="n" min="1" value="5" />
          </div>
          <div><button>Agregar</button></div>
        </form>
      </section>

      <section class="card" style="grid-column:1/-1">
        <h3>Invitaciones</h3>
        <div class="muted" style="margin-bottom:8px">Compartí el link con la persona invitada. Al aceptar, ocupa 1 asiento.</div>
        <div style="overflow:auto">
          <table>
            <thead><tr>
              <th>Email</th><th>Token</th><th>Usada</th><th>Creada</th><th>Link</th><th>Acciones</th>
            </tr></thead>
            <tbody>
              {rows_invites}
            </tbody>
          </table>
        </div>
      </section>

      <section class="card" style="grid-column:1/-1">
        <h3>Usuarios de la organización</h3>
        <div style="overflow:auto">
          <table>
            <thead><tr>
              <th>Nombre</th><th>Email</th><th>Admin</th><th>Activo</th><th>Alta</th><th>Acciones</th>
            </tr></thead>
            <tbody>
              {rows_users}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</body></html>
"""
    return HTMLResponse(html_page)


# --------------------------
# Resumen de mi organización (JSON)
# --------------------------
@router.get("/me")
def my_org_summary(user=Depends(get_current_user_cookie), db: Session = Depends(get_db)):
    if not user or not user.org_id:
        return {"org": None, "is_org_admin": False}

    org = db.query(models.Organization).get(user.org_id)
    if not org:
        return {"org": None, "is_org_admin": False}

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
    _require_org_admin(user)
    org = db.query(models.Organization).get(user.org_id)
    if not org:
        raise HTTPException(404, "Organización no encontrada")

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

# Helper para formularios HTML (POST en lugar de DELETE)
@router.post("/invites/{invite_id}/delete")
def delete_invite_post(invite_id: int, user=Depends(get_current_user_cookie), db: Session = Depends(get_db)):
    return delete_invite(invite_id, user, db)


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

    if _recalc_seats_used(db, org) >= org.seats_total:
        return HTMLResponse("<h3>No hay asientos disponibles. Contactá al administrador.</h3>", status_code=400)

    return HTMLResponse(f"""
<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Aceptar invitación — {html.escape(org.name)}</title>
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
  <h2>Unite a <strong>{html.escape(org.name)}</strong></h2>
  <p class="muted">Completá tus datos para crear tu cuenta y ocupar 1 asiento.</p>
  <div class="card">
  <form method="POST" action="/org/accept-invite">
    <input type="hidden" name="token" value="{html.escape(token)}">
    <label>Nombre</label>
    <input name="name" required>
    <label>Email</label>
    <input name="email" value="{html.escape(inv.email or '')}" required>
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

    used = _recalc_seats_used(db, org)
    if used >= org.seats_total:
        raise HTTPException(400, "No hay asientos disponibles")

    email_n = _norm_email(email)
    existing = db.query(models.User).filter(func.lower(models.User.email) == email_n).first()
    if existing:
        raise HTTPException(400, "El email ya está registrado. Iniciá sesión o usá otro email.")

    u = models.User(
        name=name.strip(),
        email=email_n,
        password_hash=get_password_hash(password),
        plan="BIZ",            # o mantener FREE/PRO y gobernar por org; a tu gusto
        role="user",
        is_admin=False,
        is_superuser=False,
        is_active=True,
        org_id=org.id,
    )
    db.add(u)
    inv.used = True
    db.flush()
    inv.used_by_user_id = u.id
    _recalc_seats_used(db, org)
    db.commit()
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
