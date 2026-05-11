import os
from pathlib import Path
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from app.security import get_current_user_cookie
from app.services.analysis_service import analyze_log
from app.services.pdf_service import generate_pdf
from app.ui import templates
from app.config import get_settings

router = APIRouter(prefix="/scanner", tags=["scanner"])

@router.post("/scan")
async def scan_logs(
    request: Request,
    log_content: str = Form(...),
    download_pdf: bool = Form(False),
    user = Depends(get_current_user_cookie)
):
    # 1. Ejecutar el análisis con el servicio corregido
    # (Asegurate de haber subido el analysis_service.py que potenciamos antes)
    results = analyze_log(
        log_content, 
        user_id=getattr(user, "id", None), 
        user_email=getattr(user, "email", None)
    )

    # 2. Si el usuario marcó la casilla de PDF
    if download_pdf:
        # Generamos el PDF. El servicio devuelve algo como "reports/archivo.pdf"
        pdf_rel_path = generate_pdf(results["summary"], filename_prefix="scan_report")
        
        # Obtenemos la ruta absoluta para que FileResponse lo encuentre en el disco
        filename = pdf_rel_path.split("/")[-1]
        full_path = Path(get_settings().REPORTS_DIR) / filename

        if not full_path.exists():
            # Fallback por si el REPORTS_DIR no es el mismo que en pdf_service
            full_path = Path("/tmp/reports") / filename

        return FileResponse(
            path=full_path,
            filename=f"reporte_alerttrail_{user.id}.pdf",
            media_type="application/pdf"
        )

    # 3. Si no quiere PDF, mostramos los resultados en la web
    # Asegurate de que scanner_results.html use la variable 'results'
    return templates.TemplateResponse(
        request=request,
        name="scanner_results.html",
        context={
            "results": results,
            "user": user,
            "lang": "es", # O el que uses por defecto
        }
    )
