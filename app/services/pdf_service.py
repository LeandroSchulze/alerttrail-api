# app/services/pdf_service.py
import os
from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import cm

def generate_pdf(results: dict, filename_prefix: str = "security_report") -> str:
    # 1. Definir la carpeta (igual que en main.py)
    folder = os.getenv("REPORTS_DIR", "./reports_data")
    reports_dir = Path(folder)
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    full_path = reports_dir / filename

    c = canvas.Canvas(str(full_path), pagesize=A4)
    width, height = A4

    # --- DISEÑO: Encabezado ---
    c.setFillColor(colors.HexColor("#0f172a")) # Azul AlertTrail
    c.rect(0, height - 3.5*cm, width, 3.5*cm, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(1.5*cm, height - 1.8*cm, "AlertTrail - Auditoría de Seguridad")
    c.setFont("Helvetica", 10)
    c.drawString(1.5*cm, height - 2.5*cm, f"Generado el: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    c.drawRightString(width - 1.5*cm, height - 1.8*cm, "REPORTE TÉCNICO")

    # --- RESUMEN DE MÉTRICAS ---
    y = height - 5*cm
    summary = results.get("summary", {})
    
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1.5*cm, y, "1. Resumen de Hallazgos")
    y -= 1*cm

    metrics = [
        ("Registros analizados:", str(summary.get("total", 0))),
        ("Inyecciones SQL (SQLi):", str(summary.get("sqli", 0))),
        ("Accesos a archivos sensibles:", str(summary.get("traversal", 0))),
        ("Nivel de Riesgo General:", summary.get("risk", "LOW").upper())
    ]

    c.setFont("Helvetica", 11)
    for label, val in metrics:
        c.drawString(2*cm, y, label)
        c.setFont("Helvetica-Bold", 11)
        # Cambiar color si el riesgo es alto
        if "Riesgo" in label and val == "HIGH": c.setFillColor(colors.red)
        c.drawRightString(width - 2*cm, y, val)
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 11)
        y -= 0.6*cm

    # --- SECCIÓN EXPLICATIVA Y RECOMENDACIONES ---
    y -= 1*cm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1.5*cm, y, "2. Análisis y Recomendaciones")
    y -= 1*cm

    # Lógica explicativa
    advices = []
    if summary.get("sqli", 0) > 0:
        advices.append(("SQL Injection", "Se detectaron intentos de manipular la base de datos. \nRECOMENDACIÓN: Use ORMs o sentencias preparadas y escape todos los caracteres especiales."))
    if summary.get("traversal", 0) > 0:
        advices.append(("Path Traversal", "Alguien intentó ver archivos internos del servidor. \nRECOMENDACIÓN: Revise los permisos de las carpetas y sanitice las rutas en su código."))
    
    if not advices:
        advices.append(("Sin Amenazas Críticas", "No se detectaron patrones de ataque conocidos. \nRECOMENDACIÓN: Mantenga sus dependencias actualizadas y monitoree logs regularmente."))

    for title, desc in advices:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(2*cm, y, f"• {title}:")
        y -= 0.5*cm
        c.setFont("Helvetica", 10)
        # Manejo de saltos de línea manual para el PDF
        for line in desc.split('\n'):
            c.drawString(2.5*cm, y, line)
            y -= 0.5*cm
        y -= 0.4*cm

    # --- EVIDENCIA DE HALLAZGOS ---
    if results.get("findings"):
        y -= 0.5*cm
        c.setFont("Helvetica-Bold", 14)
        c.drawString(1.5*cm, y, "3. Evidencia de Logs Sospechosos")
        y -= 1*cm
        c.setFont("Courier", 7)
        c.setFillColor(colors.HexColor("#450a0a")) # Rojo sangre oscuro para logs
        for line in results["findings"][:15]:
            if y < 2*cm:
                c.showPage()
                y = height - 2*cm
                c.setFont("Courier", 7)
            c.drawString(1.5*cm, y, f"> {line[:120]}")
            y -= 0.4*cm

    c.showPage()
    c.save()
    return filename # Retornamos solo el nombre del archivo
