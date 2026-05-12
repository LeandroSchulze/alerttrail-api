# app/services/pdf_service.py
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import cm
from pathlib import Path
from datetime import datetime

def generate_pdf(results: dict, filename_prefix: str = "security_report") -> str:
    # 1. Configuración de ruta
    reports_dir = Path("./reports_data")
    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    full_path = reports_dir / filename

    c = canvas.Canvas(str(full_path), pagesize=A4)
    width, height = A4

    # --- ENCABEZADO ---
    c.setFillColor(colors.HexColor("#0f172a"))
    c.rect(0, height - 3*cm, width, 3*cm, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(2*cm, height - 1.8*cm, "AlertTrail - Informe de Seguridad")
    
    c.setFont("Helvetica", 10)
    c.drawRightString(width - 2*cm, height - 1.8*cm, f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # --- RESUMEN DE RIESGO ---
    y = height - 5*cm
    risk = results['summary'].get('risk', 'low').upper()
    risk_color = colors.red if risk == "HIGH" else colors.orange if risk == "MEDIUM" else colors.green
    
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2*cm, y, "Nivel de Riesgo General:")
    c.setFillColor(risk_color)
    c.drawString(8*cm, y, risk)

    # --- TABLA DE ESTADÍSTICAS ---
    y -= 1.5*cm
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2*cm, y, "Métricas Detectadas:")
    y -= 0.8*cm
    
    stats = [
        ("Total de líneas analizadas", str(results['summary'].get('total', 0))),
        ("Inyecciones SQL (SQLi)", str(results['summary'].get('sqli', 0))),
        ("Accesos a archivos sensibles", str(results['summary'].get('traversal', 0))),
        ("Intentos SSH fallidos", str(results['summary'].get('ssh_failed', 0))),
    ]

    c.setFont("Helvetica", 11)
    for label, val in stats:
        c.drawString(2.5*cm, y, f"• {label}:")
        c.drawRightString(width - 3*cm, y, val)
        y -= 0.6*cm

    # --- EXPLICACIÓN DE AMENAZAS ---
    y -= 1*cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2*cm, y, "Glosario de Amenazas:")
    y -= 0.7*cm
    c.setFont("Helvetica-Oblique", 9)
    
    definitions = [
        ("SQL Injection:", "Intentos de ejecutar comandos en la base de datos a través de formularios o URLs."),
        ("Path Traversal:", "Intentos de acceder a archivos internos del servidor (como /etc/passwd o .env)."),
        ("Brute Force:", "Intentos repetitivos de adivinar contraseñas en servicios como SSH.")
    ]
    
    for title, desc in definitions:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(2.5*cm, y, title)
        c.setFont("Helvetica", 9)
        c.drawString(5.5*cm, y, desc)
        y -= 0.5*cm

    # --- DETALLE DE LÍNEAS SOSPECHOSAS ---
    if results.get("findings"):
        y -= 1*cm
        c.setFont("Helvetica-Bold", 12)
        c.drawString(2*cm, y, "Evidencia (Primeros 10 hallazgos):")
        y -= 0.8*cm
        c.setFont("Courier", 7)
        c.setFillColor(colors.darkred)
        
        for line in results["findings"][:10]:
            if y < 2*cm: # Nueva página si no hay espacio
                c.showPage()
                y = height - 3*cm
            c.drawString(2*cm, y, line[:110])
            y -= 0.4*cm

    c.showPage()
    c.save()
    return f"reports/{filename}"
