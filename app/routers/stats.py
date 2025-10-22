# app/routers/stats.py
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import get_current_user_cookie

router = APIRouter(tags=["stats"])

# === Detectar carpeta de reportes (coherente con otros routers) ===
_REPORTS_DIR = Path(os.getenv("REPORTS_DIR") or "app/reports")
if not _REPORTS_DIR.exists():
    alt = Path("reports")
    _REPORTS_DIR = alt if alt.exists() else _REPORTS_DIR


def _is_admin(u) -> bool:
    """
    Admin check minimalista:
    - role == 'admin'  (texto)
    - is_admin / is_superuser (booleanos)
    - is_org_admin (Admin de organización)
    """
    role = (getattr(u, "role", "") or "").lower()
    return (
        bool(getattr(u, "is_admin", False))
        or bool(getattr(u, "is_superuser", False))
        or bool(getattr(u, "is_org_admin", False))
        or role == "admin"
    )


# =========================
# Métricas con tolerancia
# =========================
def _gather_metrics(db: Session) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "users_total": None,
        "users_pro": None,
        "users_biz": None,
        "users_admins": None,
        "reports_pdfs": 0,
        "reports_last_mtime": None,
    }

    # ---- Users (si el modelo existe) ----
    try:
        from app.models import User  # type: ignore
        users = db.query(User).all()
        metrics["users_total"] = len(users)

        pro = 0
        biz = 0
        admins = 0
        for u in users:
            plan = (getattr(u, "plan", "") or "").upper()
            if plan == "PRO" or bool(getattr(u, "is_pro", False)):
                pro += 1
            if plan in {"BIZ", "EMPRESAS", "EMPRESA"}:
                biz += 1
            if _is_admin(u):
                admins += 1

        metrics["users_pro"] = pro
        metrics["users_biz"] = biz
        metrics["users_admins"] = admins
    except Exception:
        # Si no existe User o falla la consulta, dejamos None
        pass

    # ---- Reportes PDF locales ----
    try:
        if _REPORTS_DIR.exists():
            pdfs = list(_REPORTS_DIR.glob("*.pdf"))
            metrics["reports_pdfs"] = len(pdfs)
            if pdfs:
                last = max(pdfs, key=lambda p: p.stat().st_mtime)
                metrics["reports_last_mtime"] = datetime.fromtimestamp(
                    last.stat().st_mtime, tz=timezone.utc
                ).isoformat(timespec="seconds")
    except Exception:
        pass

    # ---- Descargas de reportes (si el modelo existe) últimos 30 días ----
    try:
        from app.models import ReportDownload  # type: ignore
        since = datetime.now(timezone.utc) - timedelta(days=30)
        recent = (
            db.query(ReportDownload)
            .filter(getattr(ReportDownload, "created_at", since) >= since)
            .count()
        )
        metrics["report_downloads_30d"] = int(recent)
    except Exception:
        # Campo created_at puede no existir; en ese caso ignoramos esta métrica
        metrics["report_downloads_30d"] = None

    return metrics


# =========================
# UI HTML para admins
# =========================
@router.get("/stats", response_class=HTMLResponse)
def stats_home(
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)
    if not _is_admin(user):
        return RedirectResponse(url="/dashboard?err=perm", status_code=303)

    m = _gather_metrics(db)

    def cell(v):
        return "-" if v is None else str(v)

    html = f"""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<title>Estadísticas</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
</head>
<body style="font-family:system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;background:#0b2133;color:#e5f2ff;margin:0">
  <div style="max-width:980px;margin:40px auto;padding:0 16px">
    <a href="/dashboard" style="color:#93c5fd;text-decoration:none">&larr; Volver al dashboard</a>
    <h1 style="margin:16px 0 6px">Estadísticas</h1>
    <p style="color:#bcd7f0">Sección visible para administradores.</p>

    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin-top:12px">
      <div style="background:#0f2a42;border:1px solid #133954;border-radius:14px;padding:18px">
        <h3 style="margin:0 0 8px">Usuarios</h3>
        <p style="margin:.25rem 0;color:#bcd7f0">Totales: <b>{cell(m['users_total'])}</b></p>
        <p style="margin:.25rem 0;color:#bcd7f0">PRO: <b>{cell(m['users_pro'])}</b> · BIZ/EMPRESAS: <b>{cell(m['users_biz'])}</b></p>
        <p style="margin:.25rem 0;color:#bcd7f0">Admins: <b>{cell(m['users_admins'])}</b></p>
      </div>

      <div style="background:#0f2a42;border:1px solid #133954;border-radius:14px;padding:18px">
        <h3 style="margin:0 0 8px">Reportes</h3>
        <p style="margin:.25rem 0;color:#bcd7f0">PDFs locales: <b>{cell(m['reports_pdfs'])}</b></p>
        <p style="margin:.25rem 0;color:#bcd7f0">Último PDF: <b>{cell(m['reports_last_mtime'])}</b></p>
        <p style="margin:.25rem 0;color:#bcd7f0">Descargas 30d: <b>{cell(m.get('report_downloads_30d'))}</b></p>
      </div>
    </div>

    <div style="margin-top:18px;color:#89b4e6">
      <small>Generado: {cell(m['generated_at'])} (UTC)</small>
      <span> · </span>
      <a href="/stats/data" style="color:#93c5fd">Ver JSON</a>
    </div>
  </div>
</body>
</html>
"""
    return HTMLResponse(html)


# =========================
# API JSON (para dashboard)
# =========================
@router.get("/stats/data", response_class=JSONResponse)
def stats_data(
    db: Session = Depends(get_db),
    user = Depends(get_current_user_cookie),
):
    if not user:
        return JSONResponse({"detail": "No autenticado"}, status_code=401)
    if not _is_admin(user):
        return JSONResponse({"detail": "Permiso denegado"}, status_code=403)

    return JSONResponse(_gather_metrics(db))
