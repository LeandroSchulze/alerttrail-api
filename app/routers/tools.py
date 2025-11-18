# app/routers/tools.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pathlib import Path
from typing import Optional, Dict, Any
import re

router = APIRouter(prefix="/tools", tags=["tools"])

# ---------------------------
# Helpers (UI mínimo común)
# ---------------------------
BASE_STYLE = """
:root{--bg:#f8fafc;--card:#fff;--border:#e2e8f0;--text:#0f172a;--muted:#64748b;--brand:#0ea5e9}
*{box-sizing:border-box} body{margin:0;background:var(--bg);font-family:system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;color:var(--text)}
.container{max-width:980px;margin:24px auto;padding:0 16px}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,.04);padding:18px}
h1{font-size:1.6rem;margin:0 0 12px}
h2{font-size:1.2rem;margin:16px 0 10px}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.btn{padding:10px 14px;border-radius:10px;border:1px solid var(--border);background:#fff;color:var(--text);cursor:pointer}
.btn.primary{background:var(--brand);border-color:var(--brand);color:#fff}
input,textarea{width:100%;padding:10px 12px;border:1px solid #cbd5e1;border-radius:10px;background:#f8fafc;font-size:15px}
pre{background:#0f172a0d;padding:12px;border-radius:10px;overflow:auto}
a.cardlink{display:block;text-decoration:none;color:inherit;border:1px solid var(--border);border-radius:14px;padding:14px;flex:1;min-width:260px;background:#fff}
.cardlink:hover{box-shadow:0 10px 30px rgba(15,23,42,.08);border-color:#bfdbfe;transform:translateY(-1px);transition:.15s ease;}
.pill{display:inline-block;font-size:12px;padding:3px 8px;border-radius:999px;background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe}
.muted{color:var(--muted);font-size:14px}
"""

# ---------------------------
# /tools (índice)
# ---------------------------
@router.get("/", response_class=HTMLResponse)
def tools_index() -> HTMLResponse:
    html = f"""<!doctype html><meta charset="utf-8"><title>Herramientas — AlertTrail</title>
    <style>{BASE_STYLE}</style>
    <div class="container">
      <h1>Herramientas</h1>
      <p class="muted">Utilidades rápidas de seguridad para complementar el Scanner de Logs y el Mail Scanner.</p>
      <div class="row" style="margin-top:12px">
        <a class="cardlink" href="/tools/qr-scan">
          <h2>QR Scan Seguro</h2>
          <p>Escaneá códigos QR con la cámara del dispositivo o subiendo una imagen. Si el enlace es riesgoso, te mostramos una alerta antes de abrirlo.</p>
          <span class="pill">Funciona en Chromium / Android</span>
        </a>
        <a class="cardlink" href="/tools/receipt-analyzer">
          <h2>Analizador de Tickets</h2>
          <p>Pegá el texto de un ticket o factura y te ayudamos a encontrar Total, IVA, Fecha y posibles señales de fraude.</p>
          <span class="pill">Ideal para compras online</span>
        </a>
      </div>
    </div>"""
    return HTMLResponse(html)

# ---------------------------
# /tools/qr-scan (UI)
# ---------------------------
@router.get("/qr-scan", response_class=HTMLResponse)
def tools_qr_scan() -> HTMLResponse:
    html = f"""<!doctype html><meta charset="utf-8"><title>QR Scan — AlertTrail</title>
    <link rel="stylesheet" href="/static/toast.css">
    <style>{BASE_STYLE}</style>
    <div class="container">
      <h1>QR Scan Seguro</h1>
      <div class="card">
        <div class="row">
          <button id="btnStart" class="btn primary">Iniciar cámara</button>
          <label class="btn">
            Subir imagen
            <input id="file" type="file" accept="image/*" style="display:none">
          </label>
          <a href="/tools" class="btn">Volver</a>
        </div>
        <div style="margin-top:16px;display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:16px">
          <div>
            <video id="preview" style="width:100%;border-radius:14px;border:1px solid #e2e8f0;background:#020617;min-height:220px"></video>
          </div>
          <div>
            <h2>Resultado</h2>
            <pre id="result">Aguardando lectura...</pre>
            <div class="row" style="margin-top:8px">
              <button id="openLink" class="btn primary" disabled>Abrir enlace</button>
              <button id="copyLink" class="btn" disabled>Copiar enlace</button>
            </div>
            <p class="muted" style="margin-top:8px">Si tu navegador no soporta <code>BarcodeDetector</code>, usá la opción “Subir imagen”.</p>
          </div>
        </div>
      </div>
    </div>
    <script src="/static/toast.js" defer></script>
    <script src="/static/tools_qr.js" defer></script>
    """
    return HTMLResponse(html)

# ---------------------------
# Alias de compatibilidad para enlaces antiguos
# ---------------------------
@router.get("/qr", include_in_schema=False)
def tools_qr_alias() -> RedirectResponse:
    return RedirectResponse("/tools/qr-scan", status_code=307)

@router.get("/receipt", include_in_schema=False)
def tools_receipt_alias() -> RedirectResponse:
    return RedirectResponse("/tools/receipt-analyzer", status_code=307)

# ---------------------------
# /tools/receipt-analyzer (UI)
# ---------------------------
@router.get("/receipt-analyzer", response_class=HTMLResponse)
def tools_receipt_analyzer_ui() -> HTMLResponse:
    html = f"""<!doctype html><meta charset="utf-8"><title>Analizador de Tickets — AlertTrail</title>
    <style>{BASE_STYLE}</style>
    <div class="container">
      <h1>Analizador de Tickets</h1>
      <div class="card">
        <p class="muted">Pegá el texto de un ticket (o factura) y te ayudamos a extraer <b>Total</b>, <b>IVA</b>, <b>Fecha</b> y señales de fraude.</p>
        <textarea id="txt" rows="10" placeholder="Pegá acá el texto del ticket..."></textarea>
        <div class="row" style="margin-top:10px">
          <button id="analyze" class="btn primary">Analizar</button>
          <a href="/tools" class="btn">Volver</a>
        </div>
        <div style="margin-top:12px">
          <h2>Resultado</h2>
          <pre id="result">—</pre>
        </div>
      </div>
    </div>
    <script src="/static/tools_receipt.js" defer></script>
    """
    return HTMLResponse(html)

# ---------------------------
# /tools/receipt-analyzer/api (JSON)
#   Entrada: {"text": "..."}  (sin OCR)
# ---------------------------
@router.post("/receipt-analyzer/api")
async def tools_receipt_analyzer_api(payload: Dict[str, Any]) -> JSONResponse:
    text: str = (payload or {}).get("text") or ""
    text_norm = text.replace("\r", "")
    total = None
    iva = None
    date = None

    # Totales comunes (Total $1.234,56 / TOTAL 1234.56)
    m_total = re.search(r"(?i)\btotal\b[^\d]*(\d+[.,]\d{2})", text_norm)
    if m_total:
        total = m_total.group(1)

    # IVA / impuestos
    m_iva = re.search(r"(?i)\b(iva|vat|impuesto)\b[^\d]*(\d+[.,]\d{2}|\d+%)", text_norm)
    if m_iva:
        iva = m_iva.group(2)

    # Fecha (varios formatos)
    m_date = re.search(r"(?i)\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", text_norm) or \
             re.search(r"(?i)\b(\d{4}[/-]\d{1,2}[/-]\d{1,2})\b", text_norm)
    if m_date:
        date = m_date.group(1)

    # Heurística simple de fraude
    lower = text_norm.lower()
    red_flags = []
    risk = "bajo"
    if "no reembolsable" in lower or "no refundable" in lower:
        red_flags.append("Política de ‘no reembolsable’ detectada.")
    if "pagar ahora" in lower or "pay now" in lower:
        red_flags.append("Lenguaje de urgencia detectado.")
    if "transferencia" in lower or "wire transfer" in lower:
        red_flags.append("Mencionan pago por transferencia, revisá que el destinatario sea confiable.")

    if len(red_flags) >= 2:
        risk = "alto"
    elif len(red_flags) == 1:
        risk = "medio"

    return JSONResponse({
        "ok": True,
        "total": total,
        "iva": iva,
        "date": date,
        "risk": risk,
        "red_flags": red_flags,
    })
