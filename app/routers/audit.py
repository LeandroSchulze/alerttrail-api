# app/routers/audit.py
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.i18n import get_lang, t
from app.ui import templates

# ✅ Plan guard
from app.plan_guard import get_current_user_db

router = APIRouter(prefix="/audit", tags=["audit"])

DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_REQ_FILE = DATA_DIR / "audit_requests.json"


def _load_json(path: Path, default):
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _append_audit_request(payload: Dict[str, Any]) -> None:
    data = _load_json(AUDIT_REQ_FILE, []) or []
    if not isinstance(data, list):
        data = []
    data.append(payload)
    if len(data) > 200:
        data = data[-200:]
    _save_json(AUDIT_REQ_FILE, data)


def _url_q(s: str) -> str:
    from urllib.parse import quote
    return quote(s or "", safe="")


def _require_pro_or_redirect(request: Request):
    """
    - No logueado -> login
    - Free -> upgrade
    - Pro/Admin -> ok
    """
    try:
        cu = get_current_user_db(request)
    except Exception:
        return None, RedirectResponse(url="/auth/login", status_code=302)

    if not cu.is_pro:
        nxt = "/audit/"
        return None, RedirectResponse(url=f"/billing/subscriptions?next={nxt}", status_code=302)

    return cu, None


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def audit_page_noslash(request: Request):
    return RedirectResponse(url="/audit/", status_code=302)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def audit_page(request: Request):
    lang = get_lang(request)

    cu, redir = _require_pro_or_redirect(request)
    if redir:
        return redir

    return templates.TemplateResponse(
        "audit.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
        },
    )


@router.post("/submit", response_class=HTMLResponse, include_in_schema=False)
def audit_submit(
    request: Request,
    name_org: str = Form(""),
    contact_email: str = Form(""),
    what_to_review: str = Form(""),
    team_size: str = Form(""),
    comments: str = Form(""),
):
    lang = get_lang(request)

    cu, redir = _require_pro_or_redirect(request)
    if redir:
        return redir

    name_org = (name_org or "").strip()
    contact_email = (contact_email or "").strip()
    what_to_review = (what_to_review or "").strip()
    team_size = (team_size or "").strip()
    comments = (comments or "").strip()

    missing = []
    if not name_org:
        missing.append("name_org")
    if not contact_email or "@" not in contact_email:
        missing.append("contact_email")
    if not what_to_review:
        missing.append("what_to_review")

    if missing:
        return templates.TemplateResponse(
            "audit.html",
            {
                "request": request,
                "lang": lang,
                "t": t,
                "error": t(lang, "audit.error_missing"),
                "missing": missing,
                "form": {
                    "name_org": name_org,
                    "contact_email": contact_email,
                    "what_to_review": what_to_review,
                    "team_size": team_size,
                    "comments": comments,
                },
            },
            status_code=400,
        )

    payload = {
        "ts": _now_iso(),
        "name_org": name_org,
        "contact_email": contact_email,
        "what_to_review": what_to_review,
        "team_size": team_size,
        "comments": comments,
        "ip": request.client.host if request.client else None,
        "ua": request.headers.get("user-agent"),
    }
    try:
        _append_audit_request(payload)
    except Exception:
        pass

    to_email = os.getenv("AUDIT_CONTACT_EMAIL", "info.alerttrail@gmail.com")

    subject = f"AlertTrail - Auditoría solicitada ({name_org})"
    body_lines = [
        f"Nombre/Organización: {name_org}",
        f"Email: {contact_email}",
        f"Equipo: {team_size or '-'}",
        "",
        "Qué te gustaría revisar:",
        what_to_review,
        "",
        "Comentarios adicionales:",
        comments or "-",
        "",
        f"Fecha (UTC): {payload['ts']}",
    ]
    body = "\n".join(body_lines)

    mailto = f"mailto:{to_email}?subject={_url_q(subject)}&body={_url_q(body)}"

    return templates.TemplateResponse(
        "audit.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "success": True,
            "mailto": mailto,
            "to_email": to_email,
        },
        status_code=200,
    )
