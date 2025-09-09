import os
from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from app.config import get_settings

def _ensure_reports_dir() -> Path:
    settings = get_settings()
    path = Path(settings.REPORTS_DIR)
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        tmp = Path("/tmp/reports")
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp

def generate_pdf(report_data: dict, filename_prefix: str = "analysis") -> str:
    reports_dir = _ensure_reports_dir()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{filename_prefix}_{ts}.pdf"
    pdf_fs_path = reports_dir / filename

    c = canvas.Canvas(str(pdf_fs_path), pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 16)
    c.drawString(2*cm, height - 2*cm, "AlertTrail – Reporte")
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

    return f"reports/{filename}"
