# app/routers/stats.py
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import get_current_user_cookie

router = APIRouter(tags=["stats"])

def require_admin(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_cookie(request, db=db)
    if not user:
        # sin sesión -> login
        raise HTTPException(status_code=303, detail="login", headers={"Location": "/auth/login"})
    if not getattr(user, "is_admin", False):
        # con sesión pero no admin -> dashboard
        raise HTTPException(status_code=303, detail="forbidden", headers={"Location": "/dashboard"})
    return user

@router.get("/stats", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def stats_home(_: Request):
    # Página simple (placeholder) solo visible para admin
    html = """
    <!doctype html><html lang="es"><meta charset="utf-8"><title>Estadísticas</title>
    <body style="font-family:system-ui;background:#0b2133;color:#e5f2ff;margin:0">
      <div style="max-width:980px;margin:40px auto;padding:0 16px">
        <a href="/dashboard" style="color:#93c5fd;text-decoration:none">&larr; Volver al dashboard</a>
        <h1 style="margin:16px 0 6px">Estadísticas</h1>
        <p style="color:#bcd7f0">Sección visible solo para administradores.</p>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin-top:12px">
          <div style="background:#0f2a42;border:1px solid #133954;border-radius:14px;padding:18px">
            <h3 style="margin:0 0 8px">Resumen</h3>
            <p style="margin:6px 0;color:#bcd7f0">Próximamente métricas e informes.</p>
          </div>
        </div>
      </div>
    </body></html>
    """
    return HTMLResponse(html)
