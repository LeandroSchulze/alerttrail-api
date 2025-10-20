# app/routers/payments_history.py
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.security import get_current_user_cookie
from app import models

router = APIRouter(prefix="/billing", tags=["billing"])

def _as_user(obj):
    # Convierte dict -> objeto con atributos, deja pasar objetos reales
    if isinstance(obj, dict):
        return type("U", (), obj)
    return obj

def _ensure_payments_table(db: Session):
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

@router.get("/payments", response_class=HTMLResponse)
def payments_list(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
    email: Optional[str] = Query(None, description="Filtro admin por email"),
    limit: int = Query(200, ge=1, le=1000),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)
    u = _as_user(user)

    try:
        _ensure_payments_table(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error asegurando tabla payments: {e}")

    base = "SELECT id, payment_id, user_id, email, status, currency, amount, external_reference, paid_at, created_at FROM payments"
    where = []
    params = {}

    role = getattr(u, "role", "user")
    if role != "admin":
        if getattr(u, "id", None):
            where.append("user_id = :uid")
            params["uid"] = int(u.id)
        elif getattr(u, "email", None):
            where.append("LOWER(email) = LOWER(:uem)")
            params["uem"] = str(u.email)
        else:
            where.append("1=0")
    else:
        if email:
            where.append("LOWER(email) = LOWER(:fem)")
            params["fem"] = email

    sql = base + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at DESC LIMIT :lim"
    params["lim"] = limit
    rows = db.execute(text(sql), params).fetchall()

    head_admin = "<th>Usuario</th>" if role == "admin" else ""
    body = ""
    for r in rows:
        body += (
            "<tr>"
            + (f"<td>{r.user_id or '-'}</td>" if role == "admin" else "")
            + f"<td>{r.payment_id}</td>"
            + f"<td>{(r.status or '').upper()}</td>"
            + f"<td>{r.currency or ''} {r.amount or ''}</td>"
            + f"<td>{r.email or '-'}</td>"
            + f"<td>{r.external_reference or '-'}</td>"
            + f"<td>{r.paid_at or '-'}</td>"
            + f"<td>{r.created_at or '-'}</td>"
            + "</tr>"
        )

    admin_tools = ""
    if role == "admin":
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
          {"<p>No hay pagos registrados.</p>" if not rows else
           f"<table style='width:100%;border-collapse:collapse'><thead><tr>{head_admin}<th>Payment ID</th><th>Estado</th><th>Monto</th><th>Email</th><th>External Ref</th><th>Paid at</th><th>Creado</th></tr></thead><tbody>{body}</tbody></table>"}
        </div>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(html)

# ===== JSON minimal para el front: /payments/history/mine =====
@router.get("/history/mine", response_class=JSONResponse, tags=["billing"])
def my_payments_json(
    db: Session = Depends(get_db),
    user=Depends(get_current_user_cookie),
    limit: int = Query(25, ge=1, le=200),
):
    """
    Devuelve mis últimos pagos (JSON). Corrige el caso donde `user` es dict.
    """
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    u = _as_user(user)

    try:
        _ensure_payments_table(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error asegurando tabla payments: {e}")

    # Traemos por user_id cuando está disponible; si no, por email normalizado
    rows = []
    if getattr(u, "id", None):
        sql = """
            SELECT payment_id, status, currency, amount, email, external_reference, paid_at, created_at
            FROM payments
            WHERE user_id = :uid
            ORDER BY created_at DESC
            LIMIT :lim
        """
        rows = db.execute(text(sql), {"uid": int(u.id), "lim": limit}).fetchall()
    elif getattr(u, "email", None):
        sql = """
            SELECT payment_id, status, currency, amount, email, external_reference, paid_at, created_at
            FROM payments
            WHERE LOWER(email) = LOWER(:em)
            ORDER BY created_at DESC
            LIMIT :lim
        """
        rows = db.execute(text(sql), {"em": str(u.email), "lim": limit}).fetchall()

    out = [
        {
            "payment_id": r.payment_id,
            "status": r.status,
            "currency": r.currency,
            "amount": float(r.amount) if r.amount is not None else None,
            "email": r.email,
            "external_reference": r.external_reference,
            "paid_at": r.paid_at.isoformat() if r.paid_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"ok": True, "items": out}


