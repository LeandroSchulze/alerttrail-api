# app/routers/analysis.py
import io
import os
import re
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/analysis", tags=["analysis"])

# ---------------------------
# Util: scanner sencillo
# ---------------------------
SUSP_PATTERNS = [
    (re.compile(r"\b(error|exception|traceback)\b", re.I), "Errores/Exceptions"),
    (re.compile(r"\b(401|403|500|503)\b"), "Códigos HTTP críticos"),
    (re.compile(r"\btimeout|timed out\b", re.I), "Timeouts"),
    (re.compile(r"\b(db|sqlalchemy|sqlite|psycopg|postgres)\b", re.I), "Mensajes DB"),
    (re.compile(r"\bimap|smtp|mail\b", re.I), "Mensajes de correo"),
]

def scan_text(text: str) -> List[Tuple[int, str, List[str]]]:
    """Devuelve [(line_no, line, [tags...]), ...] con hallazgos."""
    hits: List[Tuple[int, str, List[str]]] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        tags: List[str] = []
        for rx, tag in SUSP_PATTERNS:
            if rx.search(raw):
                tags.append(tag)
        if tags:
            hits.append((i, raw.strip(), tags))
    return hits

# ---------------------------
# Página simple para GET
# ---------------------------
@router.get("/generate-pdf", response_class=HTMLResponse)
def generate_pdf_get():
    """Página mínima para probar rápido desde el navegador."""
    return HTMLResponse(
        """
        <html><body style="font-family:system-ui">
          <h2>Generar PDF de análisis</h2>
          <form action="/analysis/generate-pdf" method="post" enctype="multipart/form-data">
            <p><b>Subí un log</b>: <input type="file" name="logfile"/></p>
            <p><b>O pegá texto</b>:</p>
            <textarea name="text" rows="10" cols="100" placeholder="Pega aquí tus logs..."></textarea>
            <p><button type="submit">Generar PDF</button></p>
          </form>
          <p style="opacity:.7">Tip: si no está instalado <code>reportlab</code>, se devolverá HTML en lugar de PDF.</p>
        </body></html>
        """
    )

# ---------------------------
# POST/GET: generar reporte
# ---------------------------
@router.api_route("/generate-pdf", methods=["POST"])
async def generate_pdf_post(
    logfile: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    # 1) Obtener contenido
    content = ""
    if logfile is not None:
        data = await logfile.read()
        try:
            content = data.decode("utf-8", errors="replace")
        except Exception:
            content = data.decode("latin-1", errors="replace")
    elif text:
        content = text

    if not content:
        # Como fallback, podés cargar algo de BD si tenés tabla de logs propia
        # content = "\n".join(l.message for l in db.query(AppLog).order_by(AppLog.id.desc()).limit(1000))
        return HTMLResponse("<h3>No recibí logs (archivo o texto)</h3>", status_code=400)

    # 2) Analizar
    hits = scan_text(content)
    total_lines = len(content.splitlines())
    summary = {
        "total_lines": total_lines,
        "total_hits": len(hits),
        "by_tag": {},
    }
    for _, _, tags in hits:
        for t in tags:
            summary["by_tag"][t] = summary["by_tag"].get(t, 0) + 1

    # 3) Intentar PDF con reportlab; si no está, devolver HTML
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import cm

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        width, height = A4

        y = height - 2 * cm
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, y, "Reporte de análisis de logs")
        y -= 0.8 * cm
        c.setFont("Helvetica", 10)
        c.drawString(2 * cm, y, f"Generado: {datetime.utcnow().isoformat()}Z")
        y -= 1.0 * cm

        c.setFont("Helvetica-Bold", 12)
        c.drawString(2 * cm, y, "Resumen")
        y -= 0.6 * cm
        c.setFont("Helvetica", 10)
        c.drawString(2 * cm, y, f"Total líneas: {summary['total_lines']}  |  Hallazgos: {summary['total_hits']}")
        y -= 0.6 * cm
        for tag, cnt in summary["by_tag"].items():
            c.drawString(2 * cm, y, f"- {tag}: {cnt}")
            y -= 0.5 * cm
            if y < 2 * cm:
                c.showPage(); y = height - 2 * cm

        # Detalle (limitado a ~200 líneas para que no explote)
        y -= 0.5 * cm
        c.setFont("Helvetica-Bold", 12)
        c.drawString(2 * cm, y, "Detalle")
        y -= 0.6 * cm
        c.setFont("Helvetica", 9)
        for i, line, tags in hits[:200]:
            txt = f"[{i}] ({', '.join(tags)}) {line[:120]}"
            c.drawString(2 * cm, y, txt)
            y -= 0.45 * cm
            if y < 2 * cm:
                c.showPage(); y = height - 2 * cm
                c.setFont("Helvetica", 9)

        c.showPage()
        c.save()
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="analysis-report.pdf"'},
        )
    except Exception as e:
        # Fallback HTML si no hay reportlab
        rows = "".join(
            f"<tr><td>{i}</td><td>{', '.join(tags)}</td><td style='white-space:pre'>{line}</td></tr>"
            for i, line, tags in hits[:500]
        )
        by_tag = "".join(f"<li><b>{k}</b>: {v}</li>" for k, v in summary["by_tag"].items())
        html = f"""
        <html><body style="font-family:system-ui">
          <h2>Reporte de análisis de logs (HTML)</h2>
          <p><i>Motivo: {{reportlab no disponible}} – {e}</i></p>
          <h3>Resumen</h3>
          <ul>
            <li>Total líneas: {summary['total_lines']}</li>
            <li>Hallazgos: {summary['total_hits']}</li>
            <li>Por categoría: <ul>{by_tag or '<li>(sin hallazgos)</li>'}</ul></li>
          </ul>
          <h3>Detalle (hasta 500 líneas)</h3>
          <table border="1" cellpadding="4" cellspacing="0">
            <tr><th>#</th><th>Tags</th><th>Línea</th></tr>
            {rows or '<tr><td colspan="3">Sin hallazgos</td></tr>'}
          </table>
        </body></html>
        """
        return HTMLResponse(html)
