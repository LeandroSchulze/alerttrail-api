# app/routers/reports.py
from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from app.ui import templates
from app.security import get_current_user_cookie_optional
from app.i18n import jinja_t

router = APIRouter(prefix="/reports_browser", tags=["reports"])

REPORTS_DIR = Path("app/reports")

def gv(obj, key, default=None):
    """Extrae atributos de forma segura tanto si 'obj' es un diccionario como un objeto de DB."""
    if isinstance(obj, dict): 
        return obj.get(key, default)
    return getattr(obj, key, default)

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def reports_browser(request: Request, current=Depends(get_current_user_cookie_optional)):
    if not current:
        return RedirectResponse(url="/auth/login", status_code=302)

    # 1. Identificación de Plan Segura (Evita el Error 500)
    current_plan = (gv(current, "plan") or "FREE").upper()
    role = gv(current, "role") or ""
    is_admin = role == "admin" or gv(current, "is_admin", False)
    
    # Validamos si el plan tiene acceso a reportes corporativos PRO
    is_authorized = current_plan in ("PRO", "BIZ", "BUSINESS", "EMPRESA") or is_admin

    # Detectar idioma para la pantalla de bloqueo
    lang = "es"
    try:
        from app.utils import get_lang_and_translator
        lang, _ = get_lang_and_translator(request, user=current)
    except:
        pass

    # 2. ESCUDO PARA USUARIOS FREE: Renderiza un Dashboard de venta/paywall limpio
    if not is_authorized:
        title = "Acceso Restringido" if lang == "es" else "Restricted Access"
        msg = "Los reportes avanzados corporativos están disponibles únicamente para usuarios de planes PRO y BIZ." if lang == "es" else "Advanced corporate reports are only available for PRO and BIZ plan users."
        btn_text = "Mejorar mi Plan" if lang == "es" else "Upgrade My Plan"
        back_text = "Volver al Dashboard" if lang == "es" else "Back to Dashboard"
        
        html_paywall = f"""
        <!DOCTYPE html>
        <html lang="{lang}">
        <head>
            <meta charset="UTF-8">
            <title>{title} - AlertTrail</title>
            <link rel="stylesheet" href="/static/style.css">
            <style>
                body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f4f6f9; margin: 0; padding: 0; display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
                .card {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); text-align: center; max-width: 500px; width: 90%; border-top: 5px solid #2563eb; }}
                h1 {{ color: #1e293b; margin-bottom: 16px; font-size: 24px; }}
                p {{ color: #64748b; line-height: 1.6; margin-bottom: 28px; }}
                .btn {{ background: #2563eb; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; display: inline-block; transition: background 0.2s; }}
                .btn:hover {{ background: #1d4ed8; }}
                .back-link {{ display: block; margin-top: 16px; color: #64748b; text-decoration: none; font-size: 14px; }}
                .back-link:hover {{ color: #1e293b; }}
            </style>
        </head>
        <body>
            <div class="card">
                <div style="font-size: 50px; margin-bottom: 16px;">🔒</div>
                <h1>{title}</h1>
                <p>{msg}</p>
                <a href="/billing/subscriptions" class="btn">{btn_text}</a>
                <a href="/dashboard" class="back-link">{back_text}</a>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_paywall, status_code=200)

    # 3. Código Original de carga de archivos para usuarios autorizados
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted([p.name for p in REPORTS_DIR.glob("*.pdf")], reverse=True)

    user_data = {
        "id": gv(current, "id"),
        "name": gv(current, "name", "User"),
        "email": gv(current, "email", ""),
        "plan": current_plan,
        "role": role
    }

    return templates.TemplateResponse(
        "reports.html",
        {
            "request": request,
            "files": files,
            "user": user_data,
            "current_user": user_data,
            "lang": lang,
            "t": jinja_t,
            "plan": current_plan,
        },
    )
