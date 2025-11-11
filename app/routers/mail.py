# app/routers/mail.py
import os, json, socket, imaplib, email, re, time
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from email.header import decode_header

TEMPLATES_DIR = "app/templates" if Path("app/templates").exists() else "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/mail", tags=["mail"])

DATA_DIR = Path(os.getenv("DATA_DIR", "/var/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LINK_FILE = DATA_DIR / "mail_link.json"
LAST_SUMMARY_FILE = DATA_DIR / "mail_last_summary.json"  # NUEVO: cache para el dashboard

def _env_bool(v: Optional[str], default=False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}

def _defaults_from_env() -> Dict[str, Any]:
    return dict(
        host=os.getenv("MAIL_HOST", "imap.gmail.com"),
        port=int(os.getenv("MAIL_PORT", "993") or 993),
        use_ssl=_env_bool(os.getenv("MAIL_USE_SSL", "true"), True),
        username=os.getenv("MAIL_USERNAME", ""),
        folder=os.getenv("MAIL_FOLDER", "INBOX") or "INBOX",
        mark_seen=_env_bool(os.getenv("MAIL_MARK_SEEN", "false"), False),
    )

def _load_linked() -> Dict[str, Any]:
    if LINK_FILE.exists():
        try:
            return json.loads(LINK_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_linked(data: dict) -> None:
    LINK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ====== Modelos mínimos usados por el fallback ======
class MailItem(BaseModel):
    uid: str
    from_email: Optional[str] = None
    subject: Optional[str] = None
    snippet: Optional[str] = None
    date: Optional[str] = None
    flags: Optional[List[str]] = None
    suspicious: bool = False
    score: float = 0.0
    reason: Optional[str] = None
    link: Optional[str] = None
    # opcionales (el front los ignora si no están)
    urls: Optional[List[str]] = None
    link_report: Optional[Dict[str, Any]] = None

class ScanResult(BaseModel):
    ok: bool
    login: bool
    folder: str
    unread: int
    total: int
    marked_seen: bool
    message: Optional[str] = None
    items: List[MailItem] = []

# === auth por cookie (mismo que usa main.py) ===
from app.security import get_current_user_cookie

# ====== Vistas HTML ======
@router.get("/", response_class=HTMLResponse)
def mail_index(request: Request, user=Depends(get_current_user_cookie)):
    linked = _load_linked().get(str(user["sub"]))
    ctx = {"request": request, "page_title": "Casillas de correo",
           "current_user": user, "defaults": _defaults_from_env(), "linked": linked}
    return templates.TemplateResponse("mail.html", ctx)

@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner(request: Request, user=Depends(get_current_user_cookie)):
    ctx = {"request": request, "page_title": "Mail Scanner",
           "current_user": user, "defaults": _defaults_from_env(),
           "linked": _load_linked().get(str(user["sub"]))}
    return templates.TemplateResponse("mail_scanner.html", ctx)

# ====== Vinculación simple de casilla ======
@router.get("/settings", include_in_schema=False)
def mail_settings_get():
    return RedirectResponse(url="/mail/", status_code=303)

@router.post("/settings")
async def mail_settings(request: Request, user=Depends(get_current_user_cookie)):
    addr = None
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        try:
            data = await request.json()
            addr = (data or {}).get("address")
        except Exception:
            addr = None
    else:
        try:
            form = await request.form()
            addr = form.get("address")
        except Exception:
            addr = None
        addr = addr or request.query_params.get("address")

    addr = (addr or "").strip().lower()
    if not addr or "@" not in addr:
        raise HTTPException(status_code=400, detail="Dirección inválida")

    data = _load_linked()
    data[str(user["sub"])] = {"address": addr}
    _save_linked(data)
    return RedirectResponse(url="/mail/", status_code=303)

@router.post("/connect")
async def mail_connect(request: Request, user=Depends(get_current_user_cookie)):
    return await mail_settings(request, user)

# ====== Scanner ======
# Intentamos usar el servicio “completo” (con analysis+iocs+hints). Si no está, caemos al fallback local.
try:
    from app.services.mail_scan import get_scan_summary as _svc_scan_summary, URL_RE as _SVC_URL_RE
    _HAS_SERVICE = True
except Exception:
    _svc_scan_summary = None
    _HAS_SERVICE = False
    _SVC_URL_RE = re.compile(r"https?://[^\s\"'>)]+", re.I)

def _decode_hdr(v):
    if not v:
        return ""
    if isinstance(v, bytes):
        try:
            v = v.decode("utf-8", "ignore")
        except Exception:
            v = v.decode("latin-1", "ignore")
    parts = decode_header(v)
    out = []
    for txt, enc in parts:
        if isinstance(txt, bytes):
            try:
                out.append(txt.decode(enc or "utf-8", "ignore"))
            except Exception:
                out.append(txt.decode("latin-1", "ignore"))
        else:
            out.append(txt)
    return "".join(out).strip()

# Heurística QR (para fallback)
_QR_PATTERNS = [
    r"\bcódigo\s*qr\b", r"\bqr\s*code\b", r"\bscan(ea|ea[rn])?\b.*\b(código|code)\b",
    r"\bescane(a|á)\b"
]
def _qr_hint(text: str) -> bool:
    return any(re.search(p, text or "", re.I) for p in _QR_PATTERNS)

def _score_suspicious_fallback(subj: str, snip: str):
    text = f"{subj} {snip}".lower()
    kws = ["verify", "verificar", "password", "contraseña", "urgent", "urgente",
           "invoice", "factura", "payment", "pago", "bank", "banco", "reset"]
    hits = [k for k in kws if k in text]
    if _qr_hint(text):
        hits.append("qr")
    score = min(1.0, (len(hits) * 0.2))
    reason = ", ".join(sorted(set(hits))) if hits else None
    return score, reason

def _fetch_items_fallback(imap, folder, limit=50):
    typ, data = imap.uid("search", None, "ALL")
    uids = (data[0] or b"").split() if typ == "OK" else []
    uids = uids[-limit:]
    items = []
    for uid in reversed(uids):
        try:
            typ, data = imap.uid(
                "fetch", uid,
                b"(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODY.PEEK[TEXT]<0.512>)"
            )
            if typ != "OK" or not data:
                continue
            hdr_raw = b""
            snippet_raw = b""
            for part in data:
                if not isinstance(part, tuple):
                    continue
                block = part[1] or b""
                if b"HEADER.FIELDS" in part[0]:
                    hdr_raw += block
                elif b"TEXT" in part[0]:
                    snippet_raw += block
            msg = email.message_from_bytes(hdr_raw or b"")
            from_email = _decode_hdr(msg.get("From"))
            subject = _decode_hdr(msg.get("Subject"))
            date = _decode_hdr(msg.get("Date"))
            snippet = (snippet_raw or b"").decode("utf-8", "ignore")[:250]

            score, reason = _score_suspicious_fallback(subject, snippet)
            urls = _SVC_URL_RE.findall(f"{subject} {snippet}")
            items.append(MailItem(
                uid=uid.decode(),
                from_email=from_email,
                subject=subject,
                date=date,
                snippet=snippet,
                suspicious=score >= 0.5,
                score=score,
                reason=reason,
                link=f"/mail/scanner?id={uid.decode()}",
                urls=urls or None,
            ))
        except Exception:
            continue
    return items

def _scan_impl_fallback() -> Dict[str, Any]:
    host = os.getenv("MAIL_HOST", "imap.gmail.com")
    port = int(os.getenv("MAIL_PORT", "993") or 993)
    use_ssl = _env_bool(os.getenv("MAIL_USE_SSL", "true"), True)
    username = os.getenv("MAIL_USERNAME", "")
    password = os.getenv("MAIL_PASSWORD", "")
    folder = os.getenv("MAIL_FOLDER", "INBOX") or "INBOX"
    mark_seen = _env_bool(os.getenv("MAIL_MARK_SEEN", "false"), False)

    if not username or not password:
        raise HTTPException(status_code=400, detail="Faltan MAIL_USERNAME o MAIL_PASSWORD")

    try:
        imap = imaplib.IMAP4_SSL(host, port, timeout=30) if use_ssl else imaplib.IMAP4(host, port, timeout=30)
        typ, _ = imap.login(username, password)
        if typ != "OK":
            return dict(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False,
                        message="Login IMAP falló", items=[])
        typ, _ = imap.select(folder, readonly=not mark_seen)
        if typ != "OK":
            return dict(ok=False, login=True, folder=folder, unread=0, total=0, marked_seen=False,
                        message=f"No se pudo abrir {folder}", items=[])
        typ, data = imap.search(None, "ALL")
        total = len((data[0] or b"").split()) if typ == "OK" else 0
        typ, data = imap.search(None, "UNSEEN")
        unread = len((data[0] or b"").split()) if typ == "OK" else 0

        items = _fetch_items_fallback(imap, folder)

        try:
            imap.close(); imap.logout()
        except Exception:
            pass

        return dict(ok=True, login=True, folder=folder, unread=unread, total=total,
                    marked_seen=bool(mark_seen), message=None,
                    items=[it.dict() for it in items])
    except (imaplib.IMAP4.error, socket.timeout) as e:
        return dict(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False, message=str(e), items=[])
    except Exception as e:
        return dict(ok=False, login=False, folder=folder, unread=0, total=0, marked_seen=False, message=f"Error: {e}", items=[])

# ====== Detonation opcional (no rompe si no está) ======
try:
    from app.services.link_detonation import detonate_urls as _detonate
    _HAS_DETONATION = True
except Exception:
    _detonate = None
    _HAS_DETONATION = False

@router.get("/scan")
@router.post("/scan")
def mail_scan(user=Depends(get_current_user_cookie)):
    # 1) escaneo
    if _HAS_SERVICE and _svc_scan_summary:
        defaults = _defaults_from_env()
        data = _svc_scan_summary(
            host=defaults["host"], port=defaults["port"], use_ssl=defaults["use_ssl"],
            username=os.getenv("MAIL_USERNAME", ""), password=os.getenv("MAIL_PASSWORD", ""),
            folder=defaults["folder"], mark_seen=defaults["mark_seen"], max_msgs=50
        )
    else:
        data = _scan_impl_fallback()

    # 2) detonation opcional (no bloqueante)
    if _env_bool(os.getenv("LINK_DETONATION_ENABLED", "0"), False) and _HAS_DETONATION and data.get("ok"):
        all_urls: List[str] = []
        for it in data.get("items", []):
            urls = []
            if isinstance(it, dict) and "analysis" in it:
                urls = (it.get("analysis", {}) or {}).get("iocs", {}).get("urls", []) or []
            elif isinstance(it, dict):
                urls = it.get("urls") or _SVC_URL_RE.findall(f"{it.get('subject','')} {it.get('snippet','')}")
            all_urls.extend(urls or [])

        report = _detonate(all_urls, limit=20) if all_urls else {"ok": True, "results": {}}
        data["detonation"] = report

        # resumen por item
        if report.get("results"):
            rmap = report["results"]
            for it in data.get("items", []):
                urls = []
                if isinstance(it, dict) and "analysis" in it:
                    urls = (it.get("analysis", {}) or {}).get("iocs", {}).get("urls", []) or []
                elif isinstance(it, dict):
                    urls = it.get("urls") or []
                details = []
                for u in urls:
                    if u in rmap:
                        details.append(rmap[u])
                if details:
                    it["link_report"] = {
                        "dangerous": any((d.get("susp_tld") or d.get("punycode")) for d in details),
                        "details": details[:5],
                    }

    # 3) cacheamos para el dashboard (ligero)
    try:
        out = dict(ts=int(time.time()), **data)
        LAST_SUMMARY_FILE.write_text(json.dumps(out, ensure_ascii=False))
    except Exception as _e:
        print("[mail] no pude cachear resumen:", repr(_e))

    return data

# ====== Resumen para Dashboard ======
@router.get("/summary")
def mail_summary():
    """
    Devuelve el último resumen cacheado por /mail/scan o por el scheduler (si lo invoca).
    Si aún no existe, responde ok=False.
    """
    if LAST_SUMMARY_FILE.exists():
        try:
            payload = json.loads(LAST_SUMMARY_FILE.read_text(encoding="utf-8"))
            return payload
        except Exception as e:
            return JSONResponse({"ok": False, "message": f"cache corrupta: {e}"}, status_code=500)
    return {"ok": False, "message": "Sin datos aún. Ejecutá un escaneo o esperá al scheduler."}

# ---------- scheduler que invoca main.py ----------
def start_mail_scheduler(app):
    try:
        if not _env_bool(os.getenv("SCHEDULER_ENABLED", "0"), False):
            return
        import threading, time as _time
        interval = int(os.getenv("SCHEDULER_INTERVAL_SEC", "600") or 600)

        def _job():
            uid = os.getenv("DYNO") or os.getenv("RENDER_INSTANCE_ID") or "local"
            while True:
                try:
                    # reusar la misma lógica que el endpoint
                    _ = mail_scan()  # guarda cache en LAST_SUMMARY_FILE
                    print(f"[mail][sched] uid={uid} tick OK")
                except Exception as e:
                    print("[mail][sched] error:", repr(e))
                _time.sleep(interval)

        threading.Thread(target=_job, daemon=True).start()
    except Exception as e:
        print("[mail][sched] start error:", repr(e))
