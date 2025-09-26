# app/routers/rules.py
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, HTTPException, status, Form, Path, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Session, declarative_base

from ..database import get_db, SessionLocal
from ..security import get_current_user_cookie

router = APIRouter(prefix="/rules", tags=["rules"])

# =========================
# DB (tablas simples)
# =========================
Base = declarative_base()
_engine = SessionLocal().get_bind() if hasattr(SessionLocal, "get_bind") else SessionLocal().bind

class UserRule(Base):
    __tablename__ = "user_rules"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    key = Column(String(64), index=True)       # p.ej. "subject", "sender", "contains", "regex"
    op = Column(String(32), index=True)        # "contains", "equals", "regex"
    value = Column(Text, nullable=False)       # patrón/valor
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class UserSetting(Base):
    __tablename__ = "user_settings"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    key = Column(String(64), nullable=False)
    value = Column(String(256), nullable=True)
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_setting"),)

try:
    Base.metadata.create_all(bind=_engine)
except Exception as e:
    # En deploy frío puede fallar si no hay DB todavía; no romper el arranque.
    print("[rules] aviso creando tablas:", e)

# =========================
# Helpers
# =========================
def _is_pro_or_biz(u) -> bool:
    p = (getattr(u, "plan", "") or "").upper()
    return p in {"PRO", "BIZ", "EMPRESAS", "EMPRESA"}

def _require_pro_or_biz(user) -> None:
    if not _is_pro_or_biz(user):
        # 303 + Location para redirigir a billing
        raise HTTPException(
            status_code=303,
            detail="Sólo disponible para planes PRO/EMPRESAS",
            headers={"Location": "/billing?upgrade=rules"},
        )

def _get_setting(db: Session, user_id: int, key: str, default: str = "1") -> str:
    s = db.query(UserSetting).filter(UserSetting.user_id == user_id, UserSetting.key == key).first()
    return s.value if s and s.value is not None else default

def _set_setting(db: Session, user_id: int, key: str, value: str) -> None:
    s = db.query(UserSetting).filter(UserSetting.user_id == user_id, UserSetting.key == key).first()
    if s:
        s.value = value
    else:
        s = UserSetting(user_id=user_id, key=key, value=value)
        db.add(s)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

# =========================
# Vistas/Endpoints
# =========================
@router.get("/", response_class=HTMLResponse)
def rules_index(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    _require_pro_or_biz(user)

    rules: List[UserRule] = (
        db.query(UserRule).filter(UserRule.user_id == user.id).order_by(UserRule.id.desc()).all()
    )
    use_rules = _get_setting(db, user.id, "use_rules", default="1")

    # HTML mínimo para no depender de template; podés reemplazar por templates/rules.html cuando quieras
    rows = "".join(
        f"<tr><td>{r.id}</td><td>{r.key}</td><td>{r.op}</td><td>{r.value}</td>"
        f"<td><form method='post' action='/rules/{r.id}/delete' style='display:inline'>"
        f"<button type='submit'>Eliminar</button></form></td></tr>"
        for r in rules
    )
    html = f"""
    <h1>Reglas (PRO/EMPRESAS)</h1>
    <p>Uso de reglas: <b>{"Activado" if use_rules == "1" else "Desactivado"}</b></p>
    <form method="post" action="/rules/toggle" style="margin-bottom:1rem">
      <input type="hidden" name="use_rules" value='{"0" if use_rules=="1" else "1"}'>
      <button type="submit">{"Desactivar" if use_rules=="1" else "Activar"} reglas</button>
    </form>

    <h2>Agregar regla</h2>
    <form method="post" action="/rules/add">
      <label>Campo:
        <select name="key">
          <option value="subject">subject</option>
          <option value="sender">sender</option>
          <option value="body">body</option>
          <option value="headers">headers</option>
        </select>
      </label>
      <label>Operación:
        <select name="op">
          <option value="contains">contains</option>
          <option value="equals">equals</option>
          <option value="regex">regex</option>
        </select>
      </label>
      <label>Valor/patrón: <input name="value" required></label>
      <button type="submit">Agregar</button>
    </form>

    <h2>Mis reglas</h2>
    <table border="1" cellpadding="6" cellspacing="0">
      <tr><th>ID</th><th>Campo</th><th>Op</th><th>Valor</th><th></th></tr>
      {rows if rows else "<tr><td colspan='5'>Sin reglas</td></tr>"}
    </table>

    <p><a href="/dashboard">Volver al dashboard</a></p>
    """
    return HTMLResponse(html)

@router.post("/toggle")
def rules_toggle(
    use_rules: str = Form("1"),
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    _require_pro_or_biz(user)
    _set_setting(db, user.id, "use_rules", "1" if use_rules == "1" else "0")
    return RedirectResponse(url="/rules", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/add")
def rules_add(
    key: str = Form(...),
    op: str = Form(...),
    value: str = Form(...),
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    _require_pro_or_biz(user)

    key = (key or "").strip().lower()
    op = (op or "").strip().lower()
    value = (value or "").strip()

    if key not in {"subject", "sender", "body", "headers"}:
        raise HTTPException(status_code=400, detail="key inválida")
    if op not in {"contains", "equals", "regex"}:
        raise HTTPException(status_code=400, detail="op inválida")
    if not value:
        raise HTTPException(status_code=400, detail="value requerido")

    r = UserRule(user_id=user.id, key=key, op=op, value=value)
    db.add(r)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="No se pudo guardar la regla")

    return RedirectResponse(url="/rules", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/{rule_id}/delete")
def rules_delete(
    rule_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    _require_pro_or_biz(user)

    r = db.query(UserRule).filter(UserRule.id == rule_id, UserRule.user_id == user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    db.delete(r)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="No se pudo eliminar la regla")

    return RedirectResponse(url="/rules", status_code=status.HTTP_303_SEE_OTHER)
