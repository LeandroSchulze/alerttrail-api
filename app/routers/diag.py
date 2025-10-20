# app/routers/diag.py
from __future__ import annotations

import os
import ssl
import smtplib
import socket
import sys
import platform
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import get_current_user_cookie

router = APIRouter(prefix="/internal", tags=["internal-diag"])

# ---- Helpers ---------------------------------------------------------------

def _is_admin(user) -> bool:
    role = (getattr(user, "role", "") or "").lower()
    return bool(
        role == "admin"
        or getattr(user, "is_admin", False)
        or getattr(user, "is_superuser", False)
    )

def _mask(s: Optional[str], keep:int = 4) -> str:
    if not s:
        return ""
    if len(s) <= keep:
        return "*" * len(s)
    return "*" * (len(s)-keep) + s[-keep:]

def _check_db(db: Session) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "dialect": None, "error": None}
    try:
        eng = db.get_bind()
        out["dialect"] = getattr(eng.dialect, "name", "unknown")
        db.execute(text("SELECT 1"))
        out["ok"] = True
    except Exception as e:
        out["error"] = repr(e)
    return out

def _check_dirs() -> Dict[str, Any]:
    # mismos defaults que en main.py
    static_dir  = "app/static"  if Path("app/static").exists()  else "static"
    reports_dir = "app/reports" if Path("app/reports").exists() else "reports"
    results: Dict[str, Any] = {"static": {}, "reports": {}}

    for key, d in (("static", static_dir), ("reports", reports_dir)):
        p = Path(d)
        info = {"exists": p.exists(), "writable": False, "error": None, "path": str(p)}
        try:
            p.mkdir(parents=True, exist_ok=True)
            test = p / f".write_test_{os.getpid()}"
            test.write_text("ok", encoding="utf-8")
            info["writable"] = True
            try: test.unlink()
            except Exception: pass
        except Exception as e:
            info["error"] = repr(e)
        results[key] = info
    return results

def _check_smtp() -> Dict[str, Any]:
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587") or 587)
    user = os.getenv("SMTP_USER", "")
    use_tls = (os.getenv("SMTP_TLS", "1").strip().lower() in ("1","true","yes","on"))

    out = {
        "configured": bool(host and port and user),
        "host": host,
        "port": port,
        "user": _mask(user),
        "tls": use_tls,
        "connect_ok": False,
        "login_ok": None,  # no intentamos login por seguridad
        "error": None,
    }
    if not out["configured"]:
        return out

    try:
        if use_tls:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.ehlo()
                s.starttls(context=ctx)
                s.ehlo()
                # NO hacemos login para no levantar alertas
                out["connect_ok"] = True
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.ehlo()
                out["connect_ok"] = True
    except Exception as e:
        out["error"] = repr(e)

    return out

def _check_mp() -> Dict[str, Any]:
    token = (os.getenv("MP_ACCESS_TOKEN") or "").strip()
    # Sin pegarle a la API; solo validación superficial
    return {
        "configured": bool(token),
        "token_tail": token[-6:] if token else "",
        "token_len": len(token),
        "looks_valid": bool(token and len(token) >= 20),
        "note": "No se consulta la API en este diagnóstico (solo presencia y longitud del token)."
    }

def _get_scheduler_status() -> Dict[str, Any]:
    # Intentamos importar el helper si existe
    try:
        from app.services.scheduler import scheduler_status as _scheduler_status_fn  # type: ignore
        return _scheduler_status_fn() or {}
    except Exception as e:
        return {"started": False, "error": f"scheduler import error: {e!r}"}

def _collect_runtime() -> Dict[str, Any]:
    return {
        "time_utc": datetime.utcnow().isoformat() + "Z",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "executable": sys.executable,
    }

def _list_routes(request) -> Dict[str, Any]:
    app = request.app
    routes = []
    try:
        from fastapi.routing import APIRoute
        for r in app.routes:
            if isinstance(r, APIRoute):
                routes.append({"path": r.path, "methods": sorted(list(r.methods or []))})
    except Exception:
        pass
    return {"count": len(routes), "routes": routes}

# ---- Endpoints -------------------------------------------------------------

@router.get("/diag.json", response_class=JSONResponse)
def diag_json(request, db: Session = Depends(get_db), user=Depends(get_current_user_cookie)):
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Solo administradores")

    data = {
        "ok": True,
        "runtime": _collect_runtime(),
        "db": _check_db(db),
        "dirs": _check_dirs(),
        "smtp": _check_smtp(),
        "mercado_pago": _check_mp(),
        "scheduler": _get_scheduler_status(),
        "routes": _list_routes(request),
        "envs": {
            "ENV": os.getenv("ENV") or os.getenv("ENVIRONMENT") or "",
            "DEBUG_AUTH": os.getenv("DEBUG_AUTH", ""),
            "FROM_EMAIL": os.getenv("FROM_EMAIL", ""),
            "FROM_NAME": os.getenv("FROM_NAME", ""),
            "CORS_ALLOW_ORIGINS": os.getenv("CORS_ALLOW_ORIGINS", ""),
        },
    }
    return JSONResponse(data)

@router.get("/diag", response_class=HTMLResponse)
def diag_html(request, db: Session = Depends(get_db), user=Depends(get_current_user_cookie)):
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Solo administradores")

    j = diag_json.__wrapped__(request, db, user).body  # reutilizamos el JSON
    try:
        # FastAPI JSONResponse.body es bytes
        import json as _json
        data = _json.loads(j.decode("utf-8"))
    except Exception:
        data = {"ok": False, "error": "parse json"}

    def yesno(v):
        return "✅" if v else "❌"

    html = f"""<!doctype html><meta charset="utf-8">
    <title>Internal Diag — AlertTrail</title>
    <body style="font-family:system-ui;margin:20px;max-width:980px">
      <h1>Diagnóstico interno</h1>
      <p><a href="/internal/diag.json">Ver JSON</a> · <a href="/dashboard">Dashboard</a></p>

      <h2>Runtime</h2>
      <pre style="background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;padding:12px">{data.get("runtime")}</pre>

      <h2>Base de datos</h2>
      <ul>
        <li>Conexión: <b>{yesno(data.get("db",{{}}).get("ok"))}</b></li>
        <li>Driver: <code>{data.get("db",{{}}).get("dialect")}</code></li>
        <li>Error: <code>{data.get("db",{{}}).get("error")}</code></li>
      </ul>

      <h2>Dirs</h2>
      <pre style="background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;padding:12px">{data.get("dirs")}</pre>

      <h2>SMTP</h2>
      <ul>
        <li>Config: <b>{yesno(data.get("smtp",{{}}).get("configured"))}</b></li>
        <li>Host: <code>{data.get("smtp",{{}}).get("host")}</code> · Port: <code>{data.get("smtp",{{}}).get("port")}</code> · TLS: {yesno(data.get("smtp",{{}}).get("tls"))}</li>
        <li>Connect OK: <b>{yesno(data.get("smtp",{{}}).get("connect_ok"))}</b></li>
        <li>Error: <code>{data.get("smtp",{{}}).get("error")}</code></li>
      </ul>

      <h2>Mercado Pago</h2>
      <ul>
        <li>Config: <b>{yesno(data.get("mercado_pago",{{}}).get("configured"))}</b></li>
        <li>Len token: {data.get("mercado_pago",{{}}).get("token_len")} · Tail: <code>{data.get("mercado_pago",{{}}).get("token_tail")}</code></li>
        <li>Plausible: {yesno(data.get("mercado_pago",{{}}).get("looks_valid"))}</li>
        <li>Nota: {data.get("mercado_pago",{{}}).get("note")}</li>
      </ul>

      <h2>Scheduler</h2>
      <pre style="background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;padding:12px">{data.get("scheduler")}</pre>

      <h2>Rutas ({data.get("routes",{{}}).get("count")})</h2>
      <div style="background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;padding:12px;max-height:360px;overflow:auto">
        <table style="border-collapse:collapse;width:100%">
          <thead><tr><th style="text-align:left">Path</th><th style="text-align:left">Methods</th></tr></thead>
          <tbody>
            {''.join(f"<tr><td style='border-bottom:1px solid #e5e7eb;padding:6px'>{r['path']}</td><td style='border-bottom:1px solid #e5e7eb;padding:6px'>{', '.join(r['methods'])}</td></tr>" for r in data.get("routes",{{}}).get("routes",[]))}
          </tbody>
        </table>
      </div>

      <h2>Envs</h2>
      <pre style="background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;padding:12px">{data.get("envs")}</pre>

      <p style="margin-top:24px;color:#475569">Última actualización: {datetime.utcnow().isoformat()}Z</p>
    </body>"""
    return HTMLResponse(html)
