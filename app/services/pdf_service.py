# app/services/pdf_service.py
import os
from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import cm

def generate_pdf(results: dict, filename_prefix: str = "security_report") -> str:
    # 1. Alineamos la ruta con la de main.py
    # Usamos el directorio configurado en Railway o el local por defecto
    base_reports_dir = os.getenv("REPORTS_DIR", "./reports_data")
    reports_dir = Path(base_reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{filename_prefix}_{ts}.pdf"
    pdf_path = reports_dir / filename

    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    width, height = A4

    # --- ESTILO Y ENCABEZADO ---
    c.setFillColor(colors.HexColor("#0f172a")) # Azul oscuro AlertTrail
    c.rect(0, height - 3*cm, width, 3*cm, fill=1)
    
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(1.5*cm, height - 1.8*cm, "AlertTrail")
    c.setFont("Helvetica", 12)
    c.drawString(1.5*cm, height - 2.4*cm, "Informe de Auditoría de Tráfico")
    
    c.drawRightString(width - 1.5*cm, height - 1.8*cm, "CONFIDENCIAL")
    c.setFont("Helvetica", 9)
    c.drawRightString(width - 1.5*cm, height - 2.4*cm, datetime.now().strftime("%d/%m/%Y %H:%M:%S"))

    y = height - 4.5*cm

    # --- RESUMEN EJECUTIVO ---
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1.5*cm, y, "1. Resumen Ejecutivo")
    y -= 0.8*cm
    
    summary = results.get("summary", {})
    risk_level = summary.get("risk", "LOW").upper()
    
    # Color según el riesgo
    risk_color = colors.red if risk_level == "HIGH" else colors.orange if risk_level == "MEDIUM" else colors.green
    
    c.setFont("Helvetica", 11)
    c.drawString(2*cm, y, f"Durante el análisis de {summary.get('total', 0)} registros, se determinó un nivel de riesgo:")
    c.setFillColor(risk_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(13.5*cm, y, risk_level)
    
    c.setFillColor(colors.black)
    y -= 1.2*cm

    # --- MÉTRICAS DETALLADAS ---
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1.5*cm, y, "2. Métricas de Seguridad")
    y -= 0.8*cm
    
    c.setFont("Helvetica", 11)
    metrics = [
        ("Inyecciones SQL detectadas:", str(summary.get("sqli", 0))),
        ("Accesos a archivos sensibles:", str(summary.get("traversal", 0))),
        ("Ataques de Fuerza Bruta (SSH):", str(summary.get("ssh_failed", 0))),
        ("IPs identificadas como agresoras:", str(summary.get("bruteforce_ips", 0)))
    ]
    
    for label, value in metrics:
        c.drawString(2*cm, y, label)
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(width - 2*cm, y, value)
        c.setFont("Helvetica", 11)
        y -= 0.6*cm

    y -= 1*cm

    # --- EXPLICACIÓN TÉCNICA (Lo que pedías como explicativo) ---
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1.5*cm, y, "3. Glosario y Recomendaciones")
    y -= 0.8*cm
    
    definitions = [
        ("SQL Injection:", "Intento de manipular la base de datos. Se recomienda validar todos los inputs."),
        ("Path Traversal:", "Intento de leer archivos del sistema (ej. /etc/passwd). Revisar permisos de archivos."),
        ("SSH Brute Force:", "Múltiples intentos de acceso fallidos. Se recomienda usar llaves SSH y Fail2Ban.")
    ]

    for title, desc in definitions:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(2*cm, y, title)
        c.setFont("Helvetica", 10)
        c.drawString(5.5*cm, y, desc)
        y -= 0.6*cm

    # --- EVIDENCIA ---
    if results.get("findings"):
        y -= 1*cm
        c.setFont("Helvetica-Bold", 14)
        c.drawString(1.5*cm, y, "4. Evidencia de Registros Sospechosos")
        y -= 0.8*cm
        c.setFont("Courier", 7)
        c.setFillColor(colors.darkred)
        
        for idx, line in enumerate(results["findings"][:15]): # Mostramos los primeros 15
            if y < 2*cm: # Nueva página si se acaba el espacio
                c.showPage()
                y = height - 3*cm
                c.setFont("Courier", 7)
                c.setFillColor(colors.darkred)
            
            c.drawString(1.5*cm, y, f"> {line[:120]}")
            y -= 0.4*cm

    c.showPage()
    c.save()

    return filename # Retornamos solo el nombre del archivo
