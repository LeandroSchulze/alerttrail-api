import os
from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

# Elegimos una carpeta escribible (var/data si existe, si no /tmp)
_reports_dir = Path(os.getenv("REPORTS_DIR", "/var/data/reports"))
try:
    _reports_dir.mkdir(parents=True, exist_ok=True)
except Exception:
    _reports_dir = Path("/tmp/reports")
    _reports_dir.mkdir(parents=True, exist_ok=True)

# La URL pública será /reports/...
REPORTS_URL_PREFIX = "reports"

def generate_pdf(report_data: dict, filename_prefix: str = "analysis") -> str:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{filename_prefix}_{ts}.pdf"
    pdf_fs_path = _reports_dir / filename

    c = canvas.Canvas(str(pdf_fs_path), pagesize=A4)
    width, height = A4

    # Encabezado simple
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2*cm, height - 2*cm, "AlertTrail – Reporte de Análisis")
    c.setFont("Helvetica", 10)
    c.drawRightString(width - 2*cm, height - 1.5*cm, datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))

    y = height - 4*cm
    for k, v in report_data.items():
        c.setFont("Helvetica-Bold", 11)
        c.drawString(2*cm, y, f"{k}:")
        y -= 0.6*cm
        c.setFont("Helvetica", 10)
        text_obj = c.beginText(2*cm, y)
        text_obj.setLeading(14)
        for line in str(v).split("\n"):
            text_obj.textLine(line)
        c.drawText(text_obj)
        y = text_obj.getY() - 0.6*cm
        if y < 3*cm:
            c.showPage()
            y = height - 3*cm

    c.showPage()
    c.save()

    # Devolvemos la ruta web relativa (la UI hace href="/{a.pdf_path}")
    return f"{REPORTS_URL_PREFIX}/{filename}"