# app/routers/reports.py
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import get_current_user_cookie

router = APIRouter(prefix="/reports", tags=["reports"])

# Detectar carpeta de reports igual que en main.py
_REPORTS_DIR = Path(os.getenv("REPORTS_DIR") or "app/reports")
if not _REPORTS_DIR.exists():
    alt = Path("reports")
    _REPORTS_DIR = alt if alt.exists() else _REPORTS_DIR

def _list_pdfs() -> List[Dict]:
    items: List[Dict] = []
    if not _REPORTS_DIR.exists():
        return items
    for p in sorted(_REPORTS_DIR.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True):
        st = p.stat()
        items.append({
            "name": p.name,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "url": f"/reports/{p.name}",
        })
    return items

@router.get("/", response_class=HTMLResponse)
def reports_index(request: Request, user = Depends(get_current_user_cookie), db: Session = Depends(get_db)):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    rows = "".join(
        f"<tr><td>{i+1}</td><td><a href='/reports/open/{it['name']}'>{it['name']}</a></td>"
        f"<td>{it['size']}</td><td>{it['mtime']}</td></tr>"
        for i, it in enumerate(_list_pdfs())
    ) or "<tr><td colspan='4'>Sin reportes aún</td></tr>"

    html = f"""
    <h1>Reportes PDF</h1>
    <p>Carpeta: {_REPORTS_DIR}</p>
    <table border="1" cellpadding="6" cellspacing="0">
      <tr><th>#</th><th>Archivo</th><th>Tamaño (bytes)</th><th>Fecha</th></tr>
      {rows}
    </table>
    <p><a href="/dashboard">Volver al dashboard</a></p>
    """
    return HTMLResponse(html)

@router.get("/list", response_class=JSONResponse)
def reports_list(user = Depends(get_current_user_cookie), db: Session = Depends(get_db)):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    return {"items": _list_pdfs()}

@router.get("/open/{name}", include_in_schema=False)
def reports_open(name: str, user = Depends(get_current_user_cookie), db: Session = Depends(get_db)):
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Nombre inválido")

    path = _REPORTS_DIR / name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Reporte no encontrado")

    # Tracking opcional si el modelo existe
    try:
        from ..models import ReportDownload  # type: ignore
        rec = ReportDownload(user_id=getattr(user, "id", None), filename=name, size=path.stat().st_size)
        db.add(rec); db.commit()
    except Exception:
        db.rollback()

    # Redirigimos a la ruta estática ya montada en main (/reports)
    return RedirectResponse(url=f"/reports/{name}", status_code=status.HTTP_302_FOUND)
