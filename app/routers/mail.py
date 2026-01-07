from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pathlib import Path
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

router = APIRouter(prefix="/mail", tags=["mail"])

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

MAIL_SETTINGS_PATH = DATA_DIR / "mail_settings.json"
MAIL_SCAN_PATH = DATA_DIR / "scan_last_mails.json"


def _safe_load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _safe_write_json(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_date_ts(v):
    """
    Best-effort parse to epoch seconds.
    Supports:
      - int/float epoch
      - digit string epoch
      - RFC2822 strings (parsedate_to_datetime)
      - ISO8601 strings
    """
    if v is None:
        return 0

    # numeric epoch
    if isinstance(v, (int, float)):
        return int(v)

    s = str(v).strip()
    if not s:
        return 0

    # numeric string epoch
    if s.isdigit():
        try:
            return int(s)
        except Exception:
            pass

    # RFC2822 (email date header)
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        pass

    # ISO
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0


def _verdict_from_level(level: str):
    level = (level or "").lower()
    if level == "high":
        return "ALTO"
    if level == "medium":
        return "MEDIO"
    return "BAJO"


def _danger_level_from_verdict(verdict: str):
    v = (verdict or "").strip().upper()
    if v == "ALTO":
        return "high"
    if v == "MEDIO":
        return "medium"
    return "low"


def _compute_danger_level_and_reasons(item: dict):
    """
    Simple heuristic using existing fields commonly present in mail items.
    IMPORTANT: keeps compatibility: returns danger_level + reasons list.
    """
    reasons = []
    score = 0

    subject = (item.get("subject") or "").lower()
    sender = (item.get("from") or item.get("sender") or "").lower()
    body = (item.get("snippet") or item.get("body") or "").lower()

    suspicious_keywords = [
        "verify", "verification", "password", "reset", "urgent", "account",
        "suspend", "suspended", "invoice", "payment", "bank", "security alert",
        "click", "login", "confirm", "confirmación", "verificar", "contraseña",
        "urgente", "cuenta", "suspendida", "factura", "pago", "banco",
    ]

    for kw in suspicious_keywords:
        if kw in subject or kw in body:
            score += 1
            reasons.append(f"Contiene palabra clave sospechosa: '{kw}'")

    # suspicious sender patterns
    if sender and ("no-reply" in sender or "noreply" in sender):
        score += 1
        reasons.append("Remitente tipo no-reply (común en phishing)")

    # basic link presence
    if "http://" in body:
        score += 2
        reasons.append("Contiene enlace http:// (no seguro)")
    if "https://" in body:
        score += 1
        reasons.append("Contiene enlaces (revisar destino)")

    # mismatch-ish patterns
    if ("paypal" in subject or "mercadopago" in subject or "bank" in subject or "banco" in subject) and ("gmail.com" in sender or "yahoo.com" in sender or "outlook.com" in sender):
        score += 2
        reasons.append("Asunto financiero con remitente de proveedor genérico")

    # final level
    if score >= 4:
        return "high", reasons
    if score >= 2:
        return "medium", reasons
    return "low", reasons


def _normalize_and_sort_items(items):
    """
    Ensures each item has date_ts, analysis{danger_level,reasons}, level + verdict.
    Returns newest-first.
    """
    norm = []
    for it in items or []:
        if not isinstance(it, dict):
            continue

        # date_ts
        it["date_ts"] = it.get("date_ts") or _parse_date_ts(it.get("date") or it.get("internalDate") or it.get("received_at"))

        # analysis
        analysis = it.get("analysis") or {}
        danger_level = analysis.get("danger_level") or it.get("level")

        # if only verdict exists, convert
        if not danger_level and it.get("verdict"):
            danger_level = _danger_level_from_verdict(it.get("verdict"))

        # compute if still missing
        if not danger_level:
            danger_level, reasons = _compute_danger_level_and_reasons(it)
            analysis = {"danger_level": danger_level, "reasons": reasons}
        else:
            # keep existing reasons if present, else compute
            reasons = analysis.get("reasons")
            if not reasons:
                _, reasons2 = _compute_danger_level_and_reasons(it)
                analysis = {"danger_level": (danger_level or "low").lower(), "reasons": reasons2}
            else:
                analysis = {"danger_level": (danger_level or "low").lower(), "reasons": reasons}

        it["analysis"] = analysis
        it["level"] = analysis["danger_level"]
        it["verdict"] = _verdict_from_level(analysis["danger_level"])

        norm.append(it)

    norm.sort(key=lambda x: x.get("date_ts", 0), reverse=True)
    return norm


@router.get("", response_class=HTMLResponse)
def mail_settings_page(request: Request):
    settings = _safe_load_json(MAIL_SETTINGS_PATH, default={})
    return request.app.state.templates.TemplateResponse(
        "mail.html",
        {"request": request, "settings": settings},
    )


@router.post("/save")
def save_mail_settings(
    email: str = Form(""),
    provider: str = Form(""),
    host: str = Form(""),
    port: int = Form(993),
    username: str = Form(""),
    password: str = Form(""),
    ssl: str = Form("on"),
):
    settings = {
        "email": email.strip(),
        "provider": provider.strip(),
        "host": host.strip(),
        "port": int(port) if str(port).strip() else 993,
        "username": username.strip(),
        "password": password,  # NOTE: as-is (existing behavior)
        "ssl": True if ssl == "on" else False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _safe_write_json(MAIL_SETTINGS_PATH, settings)
    return RedirectResponse(url="/mail", status_code=303)


@router.get("/scanner", response_class=HTMLResponse)
def mail_scanner_page(request: Request):
    scan = _safe_load_json(MAIL_SCAN_PATH, default={"items": []})

    # backward compatibility: normalize old scans so UI + alerts work
    items = scan.get("items") or scan.get("mails") or []
    items = _normalize_and_sort_items(items)

    # keep scan shape
    scan["items"] = items
    return request.app.state.templates.TemplateResponse(
        "mail_scanner.html",
        {"request": request, "scan": scan},
    )


@router.post("/scanner/run")
def run_mail_scan():
    """
    Placeholder scan runner that reads from existing collected mails (if any),
    or keeps last scan format. The key: we ALWAYS persist danger_level so alerts work.
    """
    scan = _safe_load_json(MAIL_SCAN_PATH, default={"items": []})
    items = scan.get("items") or scan.get("mails") or []

    # normalize + compute analysis fields
    items = _normalize_and_sort_items(items)

    new_scan = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    _safe_write_json(MAIL_SCAN_PATH, new_scan)

    return RedirectResponse(url="/mail/scanner", status_code=303)


@router.get("/scanner/json")
def scanner_json():
    scan = _safe_load_json(MAIL_SCAN_PATH, default={"items": []})
    items = scan.get("items") or scan.get("mails") or []
    items = _normalize_and_sort_items(items)
    return JSONResponse({"items": items, "ran_at": scan.get("ran_at")})
