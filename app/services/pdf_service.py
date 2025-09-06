from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from datetime import datetime
from pathlib import Path

STATIC_DIR = Path("static")
STATIC_DIR.mkdir(parents=True, exist_ok=True)

def generate_pdf(report_data: dict, filename_prefix: str = "analysis") -> str:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    pdf_path = STATIC_DIR / f"{filename_prefix}_{ts}.pdf"

    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    width, height = A4

    logo_path = STATIC_DIR / "logo.png"
    if logo_path.exists():
        c.drawImage(str(logo_path), 2*cm, height - 3*cm, width=3*cm, height=2*cm, preserveAspectRatio=True, mask='auto')
    c.setFont("Helvetica-Bold", 16)
    c.drawString(6*cm, height - 2*cm, "AlertTrail – Reporte de Análisis")

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
    return str(pdf_path)
