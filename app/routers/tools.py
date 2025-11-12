# app/routers/tools.py
import os, re, io
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/tools", tags=["tools"])

@router.get("/qr-scan", response_class=HTMLResponse)
def qr_scan_page(request: Request, mode: Optional[str] = None):
    # mode=file permite ocultar la UI de cámara si se quiere
    return templates.TemplateResponse("tools_qr.html", {"request": request, "mode": (mode or "").lower()})

@router.get("/receipt-analyzer", response_class=HTMLResponse)
def receipt_analyzer_page(request: Request):
    return templates.TemplateResponse("receipt_analyzer.html", {"request": request})

# ---------- API sencilla para analizar recibos/facturas ----------
_amount_re = re.compile(r"(?<!\w)(USD|US\$|\$|ARS|EUR|€)\s?([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})?|[0-9]+)(?!\w)")
_date_re   = re.compile(r"(?<!\d)(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})")

def _extract_text_from_pdf(data: bytes) -> str:
    # Intento 1: PyPDF2 (suele estar disponible); si no, devolvemos cadena vacía (no rompemos)
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(data))
        texts = []
        for page in reader.pages:
            try:
                texts.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(texts)
    except Exception:
        return ""

@router.post("/receipt-analyzer/api")
async def receipt_analyzer_api(file: UploadFile = File(...)) -> JSONResponse:
    name = file.filename or "archivo"
    ctype = (file.content_type or "").lower()
    raw = await file.read()

    text = ""
    if "pdf" in ctype:
        text = _extract_text_from_pdf(raw)
    else:
        # Por ahora sin OCR para imágenes (beta). No rompemos: usamos nombre/metadata como base.
        text = ""

    # Señales simples con regex sobre texto + filename
    hay_texto = bool(text.strip())
    base = f"{name}\n{text}" if text else name

    amounts = _amount_re.findall(base)
    dates   = _date_re.findall(base)

    # Heurística mínima de riesgo:
    risk = "low"
    reasons = []
    if not hay_texto and "pdf" in ctype:
        reasons.append("No se pudo extraer texto del PDF")
    if len(amounts) >= 3:
        risk = "medium"; reasons.append("Múltiples montos detectados")
    if ("transfer" in base.lower() or "transferencia" in base.lower()) and ("urgente" in base.lower()):
        risk = "high"; reasons.append("Palabras de urgencia asociadas a pago")

    # Normalizamos montos
    norm_amounts = []
    for cur, val in amounts:
        cur = cur.replace("US$", "USD").replace("$", "USD")
        norm_amounts.append({"currency": cur, "value_raw": val})

    return JSONResponse({
        "ok": True,
        "filename": name,
        "content_type": ctype,
        "extracted_text": bool(text),
        "detections": {
            "amounts": norm_amounts,
            "dates": dates,
        },
        "analysis": {
            "danger_level": risk,
            "reasons": reasons
        }
    })
