# app/routers/payments_history.py
from __future__ import annotations

import json
from typing import Optional, List

from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import text, desc
from sqlalchemy.exc import ProgrammingError, OperationalError
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import get_current_user_cookie
from app import models

router = APIRouter(tags=["billing", "payments"])

# =========================
# Helpers
# =========================
def _as_user(obj):
    if isinstance(obj, dict):
        return type("U", (), obj)
    return obj

def _is_admin(u) -> bool:
    return bool(
        ((getattr(u, "role", "") or "").lower() == "admin") or
        getattr(u, "is_admin", False) or
        getattr(u, "is_superuser", False)
    )

def _serialize_history(ph: models.PaymentHistory) -> dict:
    return {
        "id": ph.id,
        "user_id": ph.user_id,
        "provider": ph.provider,
        "provider_payment_id": ph.provider_payment_id,
        "plan": ph.plan,
        "period_months": ph.period_months,
        "amount_cents": ph.amount_cents,
        "currency": ph.currency,
        "status": ph.status,
        "description": ph.description,
        "created_at": ph.created_at.isoformat() if ph.created_at else None,
    }

def _ensure_legacy_payments_table(db: Session):
    """
    Asegura la tabla legacy `payments` (solo si aún no migraste a PaymentHistory).
    Mantiene compat con tu implementación anterior.
    """
    eng = db.get_bind()
    dialect = getattr(eng.dialect, "name", "sqlite")
    if dialect == "sqlite":
        ddl = """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY,
            payment_id VARCHAR UNIQUE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            email VARCHAR,
            status VARCHAR,
            currency VARCHAR,
            amount NUMERIC,
            external_reference VARCHAR,
            paid_at DATETIME,
            raw TEXT,
            created_at DATETIME,
            updated_at DATETIME
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_payment_id ON payments(payment_id);
        CREATE INDEX IF NOT EXISTS ix_payments_user_id ON payments(user_id);
        CREATE INDEX IF NOT EXISTS ix_payments_status ON payments(status);
        """
    else:
        ddl = """
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            payment_id VARCHAR UNIQUE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            email VARCHAR,
            status VARCHAR,
            currency VARCHAR,
            amount NUMERIC,
            external_reference VARCHAR,
            paid_at TIMESTAMPTZ,
            raw TEXT,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_payment_id ON payments(payment_id);
        CREATE INDEX IF NOT EXISTS ix_payments_user_id ON payments(user_id);
        CREATE INDEX IF NOT EXISTS ix_payments_status ON payments(status);
        """
    for stmt in ddl.split(";"):
        s = stmt.strip()
        if s:
            db.execute(text(s))
    db.commit()

def _query_legacy_payments(db: Session, *, where_sql: str, params: dict, limit: int):
    base = """
      SELECT id, payment_id, user_id, email, status, currency, amount,
             external_reference, paid_at, created_at
      FROM payments
    """
    sql = base + (" WHERE " + where_sql if where_sql else "") + " ORDER BY created_at DESC LIMIT :lim"
    params = dict(params or {})
    params["lim"] = limit
    return db.execute(text(sql), params).fetchall()

# =========================
# HTML (compat): /billing/payments
# =========================
@router.get("/billing/payments", response_class=HTMLResponse)
def payments_list_html(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
    email: Optional[str] = Query(None, description="Filtro admin por email"),
    limit: int = Query(200, ge=1, le=1000),
):
    """
    Vista HTML de pagos. Prioriza PaymentHistory; si no existe la tabla, cae a la tabla legacy `payments`.
    Permisos:
      - Admin: puede filtrar por email y ver todos.
      - No admin: sólo sus pagos (por user_id o email).
    """
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)
    u = _as_user(user)
    is_admin = _is_admin(u)

    rows_html = []
    used_legacy = False

    # 1) Intentar con PaymentHistory (ORM)
    try:
        q = db.query(models.PaymentHistory)
        if not is_admin:
            # restringir a usuario actual
            if getattr(u, "id", None):
                q = q.filter(models.PaymentHistory.user_id == int(u.id))
            elif getattr(u, "email", None):
                # Si no hay user_id (caso raro), permitimos por email vía join ligero
                # pero para simplificar, como PaymentHistory tiene user_id requerido,
                # si no hay id del usuario, no devolvemos filas.
                q = q.filter(models.PaymentHistory.user_id == -1)
        else:
            if email:
                # Filtrado por email (join liviano)
                q = q.join(models.User, models.User.id == models.PaymentHistory.user_id)\
                     .filter(models.User.email.ilike(email))
        q = q.order_by(desc(models.PaymentHistory.created_at)).limit(limit)
        items: List[models.PaymentHistory] = q.all()

        if items:
            for r in items:
                rows_html.append(
                    "<tr>"
                    + (f"<td>{r.user_id or '-'}</td>" if is_admin else "")
                    + f"<td>{r.provider_payment_id or '-'}</td>"
                    + f"<td>{(r.status or '').upper()}</td>"
                    + f"<td>{(r.currency or 'USD')} { (r.amount_cents/100.0) if r.amount_cents is not None else ''}</td>"
                    + f"<td>{'-'}</td>"  # email no está en PaymentHistory; se puede agregar join si hace falta mostrarlo.
                    + f"<td>{'-'}</td>"  # external_reference no está en PaymentHistory.
                    + f"<td>{r.created_at or '-'}</td>"
                    + f"<td>{r.created_at or '-'}</td>"
                    + "</tr>"
                )
        else:
            # Si no hay registros, seguimos para intentar legacy por si hubiera datos viejos
            pass

    except (ProgrammingError, OperationalError):
        # Tabla no existe aún → legacy
        used_legacy = True

    # 2) Si no hubo filas o la tabla no existe, usamos legacy `payments`
    if used_legacy or not rows_html:
        try:
            _ensure_legacy_payments_table(db)
            where = []
            params = {}

            if not is_admin:
                if getattr(u, "id", None):
                    where.append("user_id = :uid"); params["uid"] = int(u.id)
                elif getattr(u, "email", None):
                    where.append("LOWER(email) = LOWER(:uem)"); params["uem"] = str(u.email)
                else:
                    where.append("1=0")
            else:
                if email:
                    where.append("LOWER(email) = LOWER(:fem)"); params["fem"] = email

            rows = _query_legacy_payments(db, where_sql=" AND ".join(where), params=params, limit=limit)
            for r in rows:
                rows_html.append(
                    "<tr>"
                    + (f"<td>{r.user_id or '-'}</td>" if is_admin else "")
                    + f"<td>{r.payment_id}</td>"
                    + f"<td>{(r.status or '').upper()}</td>"
                    + f"<td>{r.currency or ''} {r.amount or ''}</td>"
                    + f"<td>{r.email or '-'}</td>"
                    + f"<td>{r.external_reference or '-'}</td>"
                    + f"<td>{r.paid_at or '-'}</td>"
                    + f"<td>{r.created_at or '-'}</td>"
                    + "</tr>"
                )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error asegurando/leyendo tabla payments: {e}")

    head_admin = "<th>Usuario</th>" if is_admin else ""
    body = "".join(rows_html) if rows_html else ""
    admin_tools = ""
    if is_admin:
        admin_tools = f"""
        <form method="get" action="/billing/payments" style="margin:0 0 12px">
          <input type="email" name="email" placeholder="filtrar por email" value="{email or ''}"
                 style="padding:8px;border-radius:8px;border:1px solid #133954;background:#0b1f2f;color:#eaf3ff" />
          <button style="padding:8px 12px;border-radius:8px;border:0;background:#0ea5e9;color:#03131c;font-weight:700">Filtrar</button>
        </form>
        """

    html = f"""
    <!doctype html><html lang="es"><meta charset="utf-8"><title>Pagos | AlertTrail</title>
    <body style="font-family:system-ui;background:#0b1f2f;color:#eaf3ff;margin:0">
      <div style="max-width:980px;margin:40px auto;padding:0 16px">
        <p><a href="/dashboard" style="color:#9ed0ff;text-decoration:none">← Volver al dashboard</a></p>
        <h1 style="margin:0 0 12px">Pagos</h1>
        {admin_tools}
        <div style="background:#0f2a42;border:1px solid #133954;border-radius:14px;padding:18px">
          {"<p>No hay pagos registrados.</p>" if not body else
           f"<table style='width:100%;border-collapse:collapse'><thead><tr>{head_admin}<th>Payment ID</th><th>Estado</th><th>Monto</th><th>Email</th><th>External Ref</th><th>Paid at</th><th>Creado</th></tr></thead><tbody>{body}</tbody></table>"}
        </div>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(html)

# =========================
# JSON: historial del usuario actual
# =========================
@router.get("/payments/history/mine", response_class=JSONResponse)
def my_payments_json(
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    try:
        q = db.query(models.PaymentHistory).filter(models.PaymentHistory.user_id == user.id)\
                                           .order_by(desc(models.PaymentHistory.created_at))
        total = q.count()
        items = q.offset(offset).limit(limit).all()
        return {"ok": True, "total": total, "limit": limit, "offset": offset, "items": [_serialize_history(x) for x in items]}
    except (ProgrammingError, OperationalError):
        # si la tabla aún no existe, devolvemos vacío (migración pendiente)
        return {"ok": True, "total": 0, "limit": limit, "offset": offset, "items": []}

# =========================
# JSON: listado admin con filtros
# =========================
@router.get("/payments/history", response_class=JSONResponse)
def list_payments_admin_json(
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
    user_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    plan: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Solo administradores")

    try:
        q = db.query(models.PaymentHistory)
        if user_id:
            q = q.filter(models.PaymentHistory.user_id == user_id)
        if status:
            q = q.filter(models.PaymentHistory.status.ilike(status))
        if plan:
            q = q.filter(models.PaymentHistory.plan.ilike(plan))
        q = q.order_by(desc(models.PaymentHistory.created_at))

        total = q.count()
        items = q.offset(offset).limit(limit).all()
        return {"ok": True, "total": total, "limit": limit, "offset": offset, "items": [_serialize_history(x) for x in items]}
    except (ProgrammingError, OperationalError):
        # si la tabla aún no existe, devolvemos vacío (migración pendiente)
        return {"ok": True, "total": 0, "limit": limit, "offset": offset, "items": []}
