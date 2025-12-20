# app/routers/mail.py
import os, json, re, imaplib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from email.header import decode_header
from email.utils import parseaddr

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.security import get_current_user_cookie
from app.ui import templates
from app.i18n import get_lang, t

router = APIRouter(prefix="/mail", tags=["mail"])

MAIL_DATA_DIR = Path(os.getenv("MAIL_DATA_DIR", "/var/data/mail"))
MAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKED_FILE = MAIL_DATA_DIR / "linked_accounts.json"
SCANS_DIR = MAIL_DATA_DIR / "scans"
SCANS_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_linked() -> Dict[str, Any]:
    return _load_json(LINKED_FILE, {})


def _defaults_from_env() -> Dict[str, Any]:
    return {
        "server": os.getenv("IMAP_SERVER", "imap.gmail.com"),
        "port": int(os.getenv("IMAP_PORT", "993")),
        "folder": os.getenv("IMAP_FOLDER", "INBOX"),
        "use_ssl": os.getenv("IMAP_SSL", "1").lower() in ("1", "true", "yes", "on"),
        "mark_read": os.getenv("IMAP_MARK_READ", "0").lower() in ("1", "true", "yes", "on"),
    }


def _compute_plan(user: Dict[str, Any]) -> str:
    role = (user or {}).get("role") or ""
    if str(role).lower() == "admin":
        try:
            user["plan"] = "PRO"
        except Exception:
            pass
        return "PRO"
    return (user or {}).get("plan") or "FREE"


def get_user(request: Request):
    return get_current_user_cookie(request)


def _user_id(user: Dict[str, Any]) -> str:
    # sub suele ser int/str. Lo normalizamos.
    return str(user.get("sub") or user.get("id") or "unknown")


def _scan_file_for(user: Dict[str, Any]) -> Path:
    return SCANS_DIR / _user_id(user) / "last_scan.json"


def _decode_mime_header(value: str) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for txt, enc in parts:
        if isinstance(txt, bytes):
            try:
                out.append(txt.decode(enc or "utf-8", errors="replace"))
            except Exception:
                out.append(txt.decode("utf-8", errors="replace"))
        else:
            out.append(txt)
    return "".join(out).strip()


def _risk_score(from_s: str, subject: str) -> Dict[str, Any]:
    """
    Scoring simple (0-100) por reglas.
    """
    score = 0
    reasons: List[str] = []

    f = (from_s or "").lower()
    s = (subject or "").lower()

    # Palabras típicas de phishing
    phishing_words = [
        ("verify", 25),
        ("verification", 20),
        ("password", 25),
        ("urgent", 20),
        ("security", 15),
        ("login", 15),
        ("suspend", 20),
        ("locked", 20),
        ("confirm", 15),
        ("update", 10),
        ("invoice", 10),
        ("payment", 12),
    ]

    for w, pts in phishing_words:
        if w in s:
            score += pts
            reasons.append(f"subject:{w}")

    # Links sospechosos en subject (a veces aparecen)
    if "http://" in s or "https://" in s:
        score += 15
        reasons.append("subject:link")

    # From raro: dominios “random” o display name extraño
    name, addr = parseaddr(from_s or "")
    domain = addr.split("@")[-1].lower() if "@" in addr else ""
    if addr and domain and domain.count(".") == 0:
        score += 10
        reasons.append("from:domain-weird")

    # Muchos números en el from/name
    if re.search(r"\d{5,}", (name or "") + " " + (addr or "")):
        score += 10
        reasons.append("from:many-digits")

    # Clamp
    score = max(0, min(100, score))
    return {"score": score, "reasons": reasons}


def _imap_connect(server: str, port: int, use_ssl: bool):
    if use_ssl:
        return imaplib.IMAP4_SSL(server, port)
    return imaplib.IMAP4(server, port)


@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_user)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)
    plan = _compute_plan(user)
    linked = _load_linked().get(_user_id(user))

    return templates.TemplateResponse(
        "mail.html",
        {
            "request": request,
            "lang": lang,
            "t": t,
            "current_user": user,
            "user": user,
            "plan": plan,
            "defaults": _defaults_from_env(),
            "linked": linked,
        },
    )


@router.get("/scanner", response_class=HTMLResponse)
import traceback
from fastapi.responses import PlainTextResponse

@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_user)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    lang = get_lang(request)
    plan = _compute_plan(user)
    linked = _load_linked().get(_user_id(user))

    last_scan = None
    scan_error = None

    scan_file = _scan_file_for(user)
    if scan_file.exists():
        data = _load_json(scan_file, None)
        if isinstance(data, dict):
            last_scan = data
            scan_error = data.get("error")

    try:
        return templates.TemplateResponse(
            "mail_scanner.html",
            {
                "request": request,
                "lang": lang,
                "t": t,
                "current_user": user,
                "user": user,
                "plan": plan,
                "defaults": _defaults_from_env(),
                "linked": linked,
                "last_scan": last_scan,
                "scan_error": scan_error,
            },
        )
    except Exception:
        # MOSTRAR el error directamente en pantalla (sin necesitar logs)
        return PlainTextResponse(traceback.format_exc(), status_code=500)


# Compat viejo
@router.get("/settings", include_in_schema=False)
def mail_settings_compat():
    return RedirectResponse(url="/mail", status_code=302)


@router.post("/settings", include_in_schema=False)
def mail_save_settings(
    request: Request,
    user=Depends(get_user),

    # IMPORTANTE: estos names deben matchear el <form>
    email: str = Form(...),
    server: str = Form(...),
    port: int = Form(993),
    username: str = Form(...),
    password: str = Form(...),
    folder: str = Form("INBOX"),
    use_ssl: Optional[str] = Form(None),
    mark_read: Optional[str] = Form(None),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    linked_all = _load_linked()
    uid = _user_id(user)

    linked_all[uid] = {
        "address": email.strip(),
        "server": server.strip(),
        "port": int(port),
        "username": username.strip(),
        "password": password,  # <- si ya tenés cifrado, acá va el encrypted blob
        "folder": (folder or "INBOX").strip(),
        "use_ssl": bool(use_ssl),     # checkbox => "on" o None
        "mark_read": bool(mark_read), # checkbox => "on" o None
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    _save_json(LINKED_FILE, linked_all)

    # volvemos a /mail
    return RedirectResponse(url="/mail", status_code=303)


@router.get("/scan", response_class=HTMLResponse)
def mail_scan(request: Request, user=Depends(get_user), limit: int = 20):
    """
    Hace scan de headers de los últimos N emails, guarda resultado en last_scan.json
    y redirige al scanner para mostrar tabla.
    """
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    limit = max(1, min(int(limit or 20), 200))
    uid = _user_id(user)

    linked = _load_linked().get(uid)
    defaults = _defaults_from_env()

    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "found": 0,
        "folder": None,
        "items": [],
        "error": None,
    }

    if not linked:
        out["error"] = "No hay una cuenta IMAP vinculada. Configurala en /mail."
        _save_json(_scan_file_for(user), out)
        return RedirectResponse(url="/mail/scanner", status_code=303)

    server = (linked.get("server") or defaults["server"] or "").strip()
    port = int(linked.get("port") or defaults["port"] or 993)
    folder = (linked.get("folder") or defaults["folder"] or "INBOX").strip()
    use_ssl = bool(linked.get("use_ssl")) if "use_ssl" in linked else bool(defaults["use_ssl"])
    username = (linked.get("username") or "").strip()
    password = linked.get("password") or ""  # si está cifrado, acá deberías descifrar

    out["folder"] = folder

    try:
        imap = _imap_connect(server, port, use_ssl)
        imap.login(username, password)

        # SELECT folder
        typ, _ = imap.select(folder, readonly=not bool(linked.get("mark_read")))
        if typ != "OK":
            raise RuntimeError(f"No se pudo abrir carpeta {folder}")

        # Buscar todos, tomar últimos N
        typ, data = imap.search(None, "ALL")
        if typ != "OK":
            raise RuntimeError("IMAP search failed")

        ids = (data[0] or b"").split()
        out["found"] = len(ids)

        last_ids = ids[-limit:] if len(ids) > limit else ids
        last_ids = list(reversed(last_ids))  # más nuevos primero

        items = []
        for msg_id in last_ids:
            # Solo headers
            typ, msg_data = imap.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ != "OK" or not msg_data:
                continue

            raw = msg_data[0][1].decode("utf-8", errors="replace")

            # parse simple
            from_line = ""
            subject_line = ""
            date_line = ""
            for line in raw.splitlines():
                if line.lower().startswith("from:"):
                    from_line = line[5:].strip()
                elif line.lower().startswith("subject:"):
                    subject_line = line[8:].strip()
                elif line.lower().startswith("date:"):
                    date_line = line[5:].strip()

            from_dec = _decode_mime_header(from_line)
            subj_dec = _decode_mime_header(subject_line)

            risk = _risk_score(from_dec, subj_dec)

            items.append({
                "id": msg_id.decode("ascii", errors="ignore") if isinstance(msg_id, (bytes, bytearray)) else str(msg_id),
                "from": from_dec,
                "subject": subj_dec,
                "date": date_line,
                "score": risk["score"],
                "reasons": risk["reasons"],
            })

        out["items"] = items
        imap.logout()

    except Exception as e:
        out["error"] = str(e)

    _save_json(_scan_file_for(user), out)
    return RedirectResponse(url="/mail/scanner", status_code=303)
