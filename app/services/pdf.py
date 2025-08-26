import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm

def ensure_dir(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)

def build_pdf(output_path: str, title: str, user_name: str, content: str, logo_path: str | None = None):
    ensure_dir(output_path)
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4

    # Header
    if logo_path and os.path.exists(logo_path):
        c.drawImage(logo_path, 1*cm, height-3*cm, width=3*cm, preserveAspectRatio=True, mask='auto')
    c.setFont("Helvetica-Bold", 18)
    c.drawString(5*cm, height-2*cm, title)

    c.setFont("Helvetica", 10)
    c.drawString(5*cm, height-2.7*cm, f"Usuario: {user_name}")

    # Body
    text = c.beginText(2*cm, height-4*cm)
    text.setFont("Helvetica", 11)
    for line in content.splitlines():
        text.textLine(line)
    c.drawText(text)

    # Footer
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(2*cm, 1.5*cm, "Generado por AlertTrail")
    c.showPage()
    c.save()
