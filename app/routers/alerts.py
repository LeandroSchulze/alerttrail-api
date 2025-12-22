from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select

from app.security import get_current_user_cookie
from app.ui import templates
from app.i18n import get_lang, t
from app.database import get_db
from app.models_pro_alerts import ProAlertQueue

router = APIRouter(prefix="", tags=["alerts"])


@router.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, user=Depends(get_current_user_cookie)):
    lang = get_lang(request)
    return templates.TemplateResponse(
        "alerts.html",
        {"request": request, "lang": lang, "t": t, "current_user": user},
    )


@router.get("/alerts/pending", include_in_schema=False)
def alerts_pending(
    request: Request,
    user=Depends(get_current_user_cookie),
    db=Depends(get_db),
):
    """
    Endpoint polled by /static/alert_clients.js
    Returns pending alerts (usually 0 or 1) and consumes them to avoid repeats.
    """
    # If not logged in, just return no alerts (avoid 401 spam in console)
    if not user or not getattr(user, "id", None):
        return JSONResponse({"ok": True, "alerts": []})

    stmt = (
        select(ProAlertQueue)
        .where(ProAlertQueue.user_id == int(user.id))
        .order_by(ProAlertQueue.created_at.asc())
        .limit(1)
    )
    row = db.execute(stmt).scalar_one_or_none()
    if not row:
        return JSONResponse({"ok": True, "alerts": []})

    payload = {
        "id": row.id,
        "title": row.title,
        "body": row.body,
        "url": row.url,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }

    # consume it so it doesn't keep popping
    try:
        db.delete(row)
        db.commit()
    except Exception:
        db.rollback()
        # Even if delete fails, don't break the UI
        return JSONResponse({"ok": True, "alerts": [payload]})

    return JSONResponse({"ok": True, "alerts": [payload]})
