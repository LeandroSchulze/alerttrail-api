# app/routers/reports.py
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import get_current_user_cookie

router = APIRouter(prefix="/reports", tags=["reports"])

# ==== Ubicación de reportes (coincidir con main.py/montaje estático) ====
# Prioriza REPORTS_DIR (ej. /var/data/reports en Render), si no, usa app/reports o reports.
_REPORTS_DIR = Path(os.getenv("REPORTS_DIR") or "app/reports")
if not _REPORTS_DIR.exists():
    alt = Path("reports")
    _REPORTS_DIR = alt if alt.exists() else _REPORTS_DIR

# ---- Helpers ----
def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n/1024:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n //= 1024
    return f"{n} B"

def _safe_pdf_name(name: str) -> str:
    """
    Valida nombre de archivo para evitar traversal, y obliga a .pdf.
    Devuelve el nombre limpio (basename) si es válido o lanza HTTPException.
    """
    if not name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Nombre inválido")
    base = Path(name).name  # quita cualquier ruta
    if Path(base).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Solo se permiten archivos PDF")
    # Evitar nombres raros (espacios extremos, nulos, etc.)
    base = base.strip()
    if not base:
        raise HTTPException(status_code=400, detail="Nombre inválido")
    return base

def _list_pdfs(limit: Optional[int] = None) -> List[Dict]:
    items: List[Dict] = []
    if not _REPORTS_DIR.exists():
        return items
    files = sorted(_REPORTS_DIR.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True)
    if limit and limit > 0:
        files = files[:limit]
    for p in files:
        st = p.stat()
        items.append({
            "name": p.name,
            "size": st.st_size,
            "size_h": _human_size(st.st_size),
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "url": f"/reports/{p.name}",  # servido por el StaticFiles montado
        })
    return items


# ==== Endpoints ====
@router.get("/", response_class=HTMLResponse)
def reports_index(
    request: Request,
    user = Depends(get_current_user_cookie),
    db: Session = Depends(get_db),
    limit: int = Query(0, ge=0, description="Opcional: limitar cantidad de elementos listados (0 = todos)"),
):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    items = _list_pdfs(limit if limit > 0 else None)
    rows = "".join(
        f"<tr>"
        f"<td>{i+1}</td>"
        f"<td><a href='/reports/open/{it['name']}'>{it['name']}</a></td>"
        f"<td>{it['size_h']}</td>"
        f"<td>{it['mtime']}</td>"
        f"</tr>"
        for i, it in enumerate(items)
    ) or "<tr><td colspan='4'>Sin reportes aún</td></tr>"

    html = f"""
    <h1>Reportes PDF</h1>
    <p>Carpeta: {_REPORTS_DIR}</p>
    <table border="1" cellpadding="6" cellspacing="0">
      <tr><th>#</th><th>Archivo</th><th>Tamaño</th><th>Fecha</th></tr>
      {rows}
    </table>
    <p><a href="/dashboard">Volver al dashboard</a></p>
    """
    return HTMLResponse(html)


@router.get("/list", response_class=JSONResponse)
def reports_list(
    user = Depends(get_current_user_cookie),
    db: Session = Depends(get_db),
    limit: int = Query(0, ge=0, description="Opcional: limitar cantidad de elementos listados (0 = todos)"),
):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    return {"items": _list_pdfs(limit if limit > 0 else None)}


@router.get("/open/{name}", include_in_schema=False)
def reports_open(
    name: str,
    user = Depends(get_current_user_cookie),
    db: Session = Depends(get_db),
):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")

    safe_name = _safe_pdf_name(name)
    path = (_REPORTS_DIR / safe_name)

    # Asegurar que el archivo esté dentro del directorio permitido
    try:
        path_resolved = path.resolve()
        base_resolved = _REPORTS_DIR.resolve()
        if base_resolved not in path_resolved.parents and path_resolved != base_resolved / safe_name:
            raise HTTPException(status_code=400, detail="Ruta inválida")
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Reporte no encontrado")

    # Tracking opcional si el modelo existe
    try:
        from app.models import ReportDownload  # type: ignore
        rec = ReportDownload(user_id=getattr(user, "id", None), filename=safe_name, size=path.stat().st_size)
        db.add(rec)
        db.commit()
    except Exception:
        db.rollback()

    # Redirigimos a la ruta estática ya montada en main (/reports)
    return RedirectResponse(url=f"/reports/{safe_name}", status_code=status.HTTP_302_FOUND)
