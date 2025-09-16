# app/routers/analysis.py
import io
import re
from datetime import datetime
from typing import List, Tuple

from fastapi import APIRouter, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/analysis", tags=["analysis"])

# ----------- Scanner sencillo -----------
SUSP_PATTERNS = [
    (re.compile(r"\b(error|exception|traceback)\b", re.I), "Errores/Exceptions"),
    (re.compile(r"\b(401|403|500|503)\b"), "HTTP críticos"),
    (re.compile(r"\btimeout|timed out\b", re.I), "Timeouts"),
    (re.compile(r"\b(db|sqlalchemy|sqlite|psycopg|postgres)\b", re.I), "Base de datos"),
    (re.compile(r"\bimap|smtp|mail\b", re.I), "Correo"),
]

def scan_text(text: str) -> List[Tuple[int, str, List[str]]]:
    hits: List[Tuple[int, str, List[str]]] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        tags = [tag for rx, tag in SUSP_PATTERNS if rx.search(raw)]
        if tags:
            hits.append((i, raw.rstrip(), tags))
    return hits

# ----------- Vista GET simple -----------
@router.get("/generate-pdf", response_class=HTMLResponse)
def generate_pdf_get():
    return HTMLResponse("""
    <html><body style="font-family:system-ui;max-width:900px;margin:40px auto">
      <h2 style="text-align:center;margin-bottom:6px">Generar PDF de análisis</h2>
      <p style="text-align:center;opacity:.7">El PDF incluye marca de agua <b>AlertTrail</b> y tablas centradas.</p>
      <form action="/analysis/generate-pdf" method="post" enctype="multipart/form-data"
            style="display:grid;gap:12px;margin-top:18px">
        <label><b>Subí un log:</b> <input type="file" name="logfile"/></label>
        <label><b>O pegá texto:</b></label>
        <textarea name="text" rows="10" cols="100" placeholder="Pega aquí tus logs..."></textarea>
        <button type="submit" style="padding:10px 14px">Generar PDF</button>
      </form>
    </body></html>
    """)

# ----------- Generador PDF -----------
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
        return HTMLResponse("<h3>No recibí logs (archivo o texto)</h3>", status_code=400)

    # 2) Analizar
    hits = scan_text(content)
    summary_counts = {}
    for _, _, tags in hits:
        for t in tags:
            summary_counts[t] = summary_counts.get(t, 0) + 1

    # 3) PDF bonito con marca de agua (fallback HTML si falta reportlab)
    try:
        # --- imports perezosos ---
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        buf = io.BytesIO()

        # Doc config con márgenes simétricos
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm
        )
        width, height = A4
        styles = getSampleStyleSheet()
        Title = ParagraphStyle(
            'TitleCentered',
            parent=styles['Title'],
            alignment=1,  # center
            fontSize=20, leading=24, spaceAfter=12
        )
        Subtle = ParagraphStyle('Subtle', parent=styles['Normal'], alignment=1, textColor=colors.grey)

        # ---------- marca de agua + footer ----------
        def on_page(canvas, _doc):
            # Marca de agua "AlertTrail" diagonal, centrada
            canvas.saveState()
            canvas.setFont("Helvetica-Bold", 60)
            canvas.setFillColorRGB(0.85, 0.85, 0.85)  # gris clarito (sin alpha)
            canvas.translate(width/2.0, height/2.0)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, "AlertTrail")
            canvas.restoreState()

            # Footer con número de página centrado
            canvas.saveState()
            canvas.setFont("Helvetica", 9)
            canvas.setFillColor(colors.grey)
            canvas.drawCentredString(width/2.0, 1.2*cm, f"Página {_doc.page}")
            canvas.restoreState()

        # ---------- contenido ----------
        story = []
        story.append(Paragraph("Reporte de análisis de logs", Title))
        story.append(Paragraph(datetime.utcnow().strftime("Generado: %Y-%m-%d %H:%M UTC"), Subtle))
        story.append(Spacer(1, 12))

        # Resumen (tabla centrada)
        res_data = [["Categoría", "Cantidad"]]
        if summary_counts:
            for k, v in sorted(summary_counts.items(), key=lambda x: (-x[1], x[0])):
                res_data.append([k, v])
        else:
            res_data.append(["(sin hallazgos)", 0])

        res_table = Table(res_data, hAlign='CENTER')
        res_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1f2937")),  # encabezado
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor("#f3f4f6"), colors.white]),
            ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(res_table)
        story.append(Spacer(1, 18))

        # Detalle (limitado para no explotar el PDF)
        det_data = [["Línea", "Tags", "Contenido"]]
        for i, line, tags in hits[:500]:
            det_data.append([i, ", ".join(tags), line[:300]])

        det_table = Table(det_data, colWidths=[2*cm, 5*cm, None], hAlign='CENTER')
        det_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#111827")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,0), 'CENTER'),
            ('ALIGN', (0,1), (0,-1), 'CENTER'),  # columna # centrada
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('GRID', (0,0), (-1,-1), 0.25, colors.lightgrey),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f9fafb")]),
            ('FONTSIZE', (0,0), (-1,-1), 9),
        ]))
        story.append(det_table)

        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="analysis-report.pdf"'},
        )

    except Exception as e:
        # Fallback HTML si falta reportlab o algo falla
        rows = "".join(
            f"<tr><td>{i}</td><td>{', '.join(tags)}</td><td style='white-space:pre-wrap'>{line}</td></tr>"
            for i, line, tags in hits[:500]
        )
        by_tag = "".join(f"<li><b>{k}</b>: {v}</li>" for k, v in summary_counts.items())
        html = f"""
        <html><body style="font-family:system-ui;max-width:1000px;margin:40px auto">
          <h2 style="text-align:center">Reporte de análisis de logs (HTML)</h2>
          <p style="text-align:center;opacity:.7">No se pudo generar PDF (falta reportlab o error). Detalle: {e}</p>
          <h3>Resumen</h3>
          <ul>
            <li>Hallazgos: {sum(summary_counts.values())}</li>
            <li>Por categoría: <ul>{by_tag or '<li>(sin hallazgos)</li>'}</ul></li>
          </ul>
          <h3>Detalle (hasta 500 líneas)</h3>
          <table border="1" cellpadding="4" cellspacing="0" style="width:100%">
            <tr style="background:#111827;color:#fff"><th>#</th><th>Tags</th><th>Línea</th></tr>
            {rows or '<tr><td colspan="3">Sin hallazgos</td></tr>'}
          </table>
        </body></html>
        """
        return HTMLResponse(html)
