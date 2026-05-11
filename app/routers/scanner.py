import os
from pathlib import Path
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse
from app.security import get_current_user_cookie_optional
from app.services.analysis_service import analyze_log
from app.services.pdf_service import generate_pdf
from app.ui import templates
from app.i18n import get_lang, t # Aseguramos que cargue las traducciones

router = APIRouter(prefix="/scanner", tags=["scanner"])

@router.post("/scan")
async def scan_logs(
    request: Request,
    log_content: str = Form(...),
    download_pdf: bool = Form(False),
    user = Depends(get_current_user_cookie_optional)
):
    # 1. Ejecutar el análisis
    results = analyze_log(
        log_content, 
        user_id=getattr(user, "id", None), 
        user_email=getattr(user, "email", None)
    )

    # 2. Si el usuario quiere el PDF
    if download_pdf:
        # El servicio genera el PDF y devuelve la ruta relativa (ej: "reports/archivo.pdf")
        pdf_url = generate_pdf(results["summary"], filename_prefix="scan_report")
        
        # Opcional: Si el servicio devuelve solo el nombre, armamos la URL
        # pdf_url = f"/reports/{pdf_filename}" 

        # Cargamos tu plantilla pdf_ready.html
        return templates.TemplateResponse(
            request=request,
            name="pdf_ready.html",
            context={
                "request": request,
                "lang": get_lang(request),
                "t": t,
                "url": f"/{pdf_url}", # Importante: le pasamos la URL al botón del HTML
                "user": user
            }
        )

    # 3. Si no quiere PDF, mostramos resultados en pantalla (necesitás esta otra plantilla)
    return templates.TemplateResponse(
        request=request,
        name="scanner_results.html",
        context={
            "request": request,
            "results": results,
            "user": user,
            "lang": get_lang(request),
            "t": t
        }
    )
