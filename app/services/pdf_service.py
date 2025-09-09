from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib import colors

def generate_pdf(user_email: str, analysis: dict) -> bytes:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    W, H = A4
    x, y = 2*cm, H - 2*cm

    def writeln(text, size=12, color=colors.black, dy=14):
        nonlocal y
        c.setFillColor(color)
        c.setFont("Helvetica", size)
        c.drawString(x, y, text)
        y -= dy

    # Encabezado
    writeln("AlertTrail – Reporte", size=18)
    writeln("")

    # Meta
    writeln(f"Usuario: {user_email}", size=12)
    writeln("")

    # Resumen
    summary = analysis.get("summary", {})
    writeln("Resumen:", size=14)
    writeln(f"- Líneas analizadas: {summary.get('total_lines', 0)}")
    writeln(f"- SSH fallidos: {summary.get('ssh_failed', 0)}")
    writeln(f"- SSH exitosos: {summary.get('ssh_accepted', 0)}")
    writeln(f"- Intentos fuerza bruta (IPs): {summary.get('bruteforce_ips', 0)}")
    writeln(f"- Patrones SQLi: {summary.get('sqli', 0)}")
    writeln(f"- Patrones XSS: {summary.get('xss', 0)}")
    risk = summary.get("risk", "low")
    color = colors.red if risk=="high" else (colors.orange if risk=="medium" else colors.green)
    writeln(f"- Riesgo estimado: {risk.upper()}", color=color)
    writeln("")

    # Hallazgos
    writeln("Hallazgos:", size=14)
    for f in analysis.get("findings", [])[:40]:  # límite por página
        t = f.get("type", "finding")
        sev = f.get("severity", "low").upper()
        ip = f.get("ip", "")
        user = f.get("user", "")
        note = f.get("note", "")
        line = f.get("line", "")
        writeln(f"* [{sev}] {t} {('(ip ' + ip + ')') if ip else ''} {('(user ' + user + ')') if user else ''}".strip())
        if note:
            writeln(f"  - {note}", size=10)
        if line:
            # recortar líneas largas
            snip = (line[:110] + "…") if len(line) > 110 else line
            writeln(f"  - {snip}", size=9, color=colors.grey)
        if y < 3*cm:
            c.showPage(); y = H - 2*cm

    c.showPage()
    c.save()
    pdf = buffer.getvalue()
    buffer.close()
    return pdf
