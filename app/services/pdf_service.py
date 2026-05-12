# app/services/pdf_service.py
import os
from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import cm

def generate_pdf(results: dict, filename_prefix: str = "security_report") -> str:
    # 1. Usar la misma carpeta que main.py
    folder = os.getenv("REPORTS_DIR", "./reports_data")
    reports_dir = Path(folder)
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    full_path = reports_dir / filename

    c = canvas.Canvas(str(full_path), pagesize=A4)
    width, height = A4

    # --- ENCABEZADO ESTILO CYBER ---
    c.setFillColor(colors.HexColor("#0f172a")) # Dark Navy
    c.rect(0, height - 3.5*cm, width, 3.5*cm, fill=1)
    
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(1.5*cm, height - 1.8*cm, "AlertTrail")
    c.setFont("Helvetica", 12)
    c.drawString(1.5*cm, height - 2.5*cm, "Informe de Auditoría de Seguridad")
    
    c.drawRightString(width - 1.5*cm, height - 1.8*cm, "ESTADO: PROTEGIDO")
    c.setFont("Helvetica", 8)
    c.drawRightString(width - 1.5*cm, height - 2.5*cm, f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # --- RESUMEN DE RIESGO ---
    y = height - 5*cm
    summary = results.get("summary", {})
    risk = summary.get("risk", "low").upper()
    color_risk = colors.red if risk == "HIGH" else colors.orange if risk == "MEDIUM" else colors.green

    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1.5*cm, y, "1. Evaluación de Riesgo")
    y -= 1*cm
    
    c.setFont("Helvetica", 12)
    c.drawString(2*cm, y, "Nivel detectado:")
    c.setFillColor(color_risk)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(5.5*cm, y, risk)
    
    y -= 1.5*cm
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1.5*cm, y, "2. Hallazgos Técnicos")
    y -= 0.8*cm

    # --- TABLA DE MÉTRICAS ---
    c.setFont("Helvetica", 11)
    metrics = [
        ("Registros procesados:", str(summary.get("total", 0))),
        ("Inyecciones SQL (SQLi):", str(summary.get("sqli", 0))),
        ("Intento de acceso a archivos:", str(summary.get("traversal", 0))),
        ("Ataques de Fuerza Bruta:", str(summary.get("ssh_failed", 0)))
    ]
    
    for label, val in metrics:
        c.drawString(2*cm, y, label)
        c.drawRightString(width - 2*cm, y, val)
        y -= 0.6*cm

    # --- SECCIÓN EXPLICATIVA (NUEVO) ---
    y -= 1*cm
    c.setStrokeColor(colors.lightgrey)
    c.line(1.5*cm, y, width - 1.5*cm, y)
    y -= 1*cm
    
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1.5*cm, y, "3. Recomendaciones de Seguridad")
    y -= 0.8*cm
    
    c.setFont("Helvetica", 10)
    advices = []
    if summary.get("sqli", 0) > 0:
        advices.append("• SQLi detectado: Implementar sentencias preparadas (ORM) y validar inputs.")
    if summary.get("traversal", 0) > 0:
        advices.append("• Path Traversal: Sanitizar rutas de archivos y restringir permisos del sistema.")
    if summary.get("ssh_failed", 0) > 5:
        advices.append("• Fuerza Bruta: Cambiar puerto SSH predeterminado y activar Fail2Ban.")
    
    if not advices:
        advices.append("• No se detectaron anomalías críticas. Mantenga el sistema actualizado.")

    for advice in advices:
        c.drawString(2*cm, y, advice)
        y -= 0.5*cm

    # --- EVIDENCIA ---
    if results.get("findings"):
        y -= 1.5*cm
        c.setFont("Helvetica-Bold", 14)
        c.drawString(1.5*cm, y, "4. Evidencia Extraída")
        y -= 0.8*cm
        c.setFont("Courier", 7)
        c.setFillColor(colors.HexColor("#7f1d1d")) # Rojo oscuro para logs
        for line in results["findings"][:15]:
            if y < 3*cm: 
                c.showPage()
                y = height - 2*cm
                c.setFont("Courier", 7)
            c.drawString(1.5*cm, y, f"> {line[:120]}")
            y -= 0.4*cm

    c.showPage()
    c.save()
    return filename # Solo devolvemos el nombre para evitar conflictos de rutas
