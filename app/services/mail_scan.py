# app/services/mail_scan.py
import imaplib, email, re, unicodedata
from email.header import decode_header, make_header
from typing import List, Tuple, Dict, Any, Optional

# ---------------- Reglas / Heurísticas ----------------
SUSP_ATTACH_EXT = {
    ".exe", ".js", ".vbs", ".scr", ".bat", ".cmd", ".ps1",
    ".jar", ".lnk", ".msi", ".reg", ".hta", ".apk", ".dmg", ".pkg",
    ".iso", ".img", ".bin", ".dll", ".com"
}
# extensiones con doble extensión engañosa
DOUBLE_EXT_RE = re.compile(r"\.(pdf|docx?|xlsx?|pptx?)\.(zip|rar|7z|exe|js)$", re.I)

PHISH_PATTERNS = [
    r"verifica tu cuenta", r"tu cuenta será suspendida", r"urgente",
    r"confirma tu contraseña", r"actualiza tu método de pago", r"has sido seleccionado",
    r"transferencia pendiente", r"adjunto factura", r"comprobante de pago",
    r"factura vencida", r"bloqueado por seguridad"
]

# --- NUEVO: patrones simples de QR-phishing
QR_PATTERNS = [
    r"\bcódigo\s*qr\b", r"\bqr\s*code\b", r"\bscan(ea|ea[rn])?\b.*\b(código|code)\b",
    r"\bescane(a|á)\b", r"paga(r)?\b.*\bqr\b", r"autenticaci[oó]n\b.*\bqr\b"
]

URL_RE = re.compile(r"https?://[^\s\"'>)]+", re.I)
OTP_RE = re.compile(r"\b(\d{6})\b")

# dominios y TLDs sospechosos
SUSP_TLDS = (".zip", ".mov")

# NUEVO: punycode / IDN
PUNYCODE_RE = re.compile(r"//[^/\s]*xn--", re.I)

def _has_qr_hint(text: str, html: str) -> bool:
    blob = f"{text or ''} {html or ''}".lower()
    if any(re.search(p, blob, re.I) for p in QR_PATTERNS):
        return True
    # heurística básica por filename/alt en <img>
    if re.search(r"<img[^>]+(alt|src)=['\"][^'\"]*(qr|codigo|c[oó]digo)[^'\"]*['\"]", html or "", re.I):
        return True
    return False

def _has_punycode(urls: List[str]) -> bool:
    return any(PUNYCODE_RE.search(u) for u in urls)

# ---------------- Utilidades ----------------
def _decode_header(val: Any) -> str:
    try:
        return str(make_header(decode_header(val))) if val else ""
    except Exception:
        return str(val or "")

def _get_filename(part) -> str:
    filename = part.get_filename()
    return _decode_header(filename)

def _collect_parts(msg) -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Devuelve (texto, html, attachments[]) donde cada attachment es:
    {filename, content_type, size}
    """
    text, html = "", ""
    atts: List[Dict[str, Any]] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get("Content-Disposition") or "").lower()

            if ctype == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True) or b""
                try:
                    text += payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                except Exception:
                    text += payload.decode("latin1", errors="ignore")
            elif ctype == "text/html" and "attachment" not in disp:
                payload = part.get_payload(decode=True) or b""
                try:
                    html += payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                except Exception:
                    html += payload.decode("latin1", errors="ignore")
            else:
                # adjuntos
                fname = _get_filename(part)
                if "attachment" in disp or fname:
                    payload = part.get_payload(decode=True) or b""
                    atts.append({
                        "filename": fname,
                        "content_type": ctype,
                        "size": len(payload)
                    })
    else:
        payload = msg.get_payload(decode=True) or b""
        try:
            text = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
        except Exception:
            text = payload.decode("latin1", errors="ignore")

    return text, html, atts


def _score_email(subject: str, sender: str, text: str, html: str,
                 atts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Devuelve un dict con:
      danger_level: low / medium / high
      reasons: lista de motivos
      iocs: {urls, otp_codes}
      hints: {qr_phishing?: bool, punycode?: bool}   # NUEVO (no oblig.)
    """
    reasons: List[str] = []
    iocs: Dict[str, Any] = {"urls": [], "otp_codes": []}
    hints: Dict[str, Any] = {}
    danger = 0

    # URLs
    all_text = " ".join([subject or "", sender or "", text or "", html or ""])
    urls = URL_RE.findall(all_text)
    iocs["urls"] = urls
    if any(u.lower().endswith(SUSP_TLDS) for u in urls):
        reasons.append("URLs con TLDs sospechosos (.zip/.mov)")
        danger += 2

    # NUEVO: punycode / IDN
    if _has_punycode(urls):
        reasons.append("Dominio punycode (IDN) detectado")
        hints["punycode"] = True
        danger += 2

    # Palabras típicas de phishing
    joined = (subject + " " + text).lower()
    if any(re.search(pat, joined, re.I) for pat in PHISH_PATTERNS):
        reasons.append("Patrones típicos de phishing")
        danger += 2

    # OTP expuesto
    otps = OTP_RE.findall(joined)
    if otps:
        iocs["otp_codes"] = otps
        reasons.append("Código OTP expuesto en el cuerpo")
        danger += 1

    # Adjuntos sospechosos
    for a in atts:
        fname = (a.get("filename") or "").lower()
        if not fname:
            continue
        if any(fname.endswith(ext) for ext in SUSP_ATTACH_EXT):
            reasons.append(f"Adjunto ejecutable/sospechoso: {fname}")
            danger += 3
        if DOUBLE_EXT_RE.search(fname):
            reasons.append(f"Doble extensión riesgosa: {fname}")
            danger += 2
        if fname.endswith(".zip") and a.get("size", 0) > 0:
            reasons.append(f"Adjunto comprimido: {fname}")
            danger += 1

    # NUEVO: QR-phishing (heurístico)
    if _has_qr_hint(text, html):
        reasons.append("Posible intento de QR-phishing")
        hints["qr_phishing"] = True
        danger += 2

    # Clasificación de riesgo
    if danger >= 5:
        level = "high"
    elif danger >= 2:
        level = "medium"
    else:
        level = "low"

    return {"danger_level": level, "reasons": reasons, "iocs": iocs, "hints": hints}


# ---------------- IMAP helpers ----------------
class IMAPClient:
    def __init__(self, host: str, port: int = 993, use_ssl: bool = True):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.conn: Optional[imaplib.IMAP4] = None

    def __enter__(self):
        self.conn = imaplib.IMAP4_SSL(self.host, self.port) if self.use_ssl else imaplib.IMAP4(self.host, self.port)
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.conn:
                self.conn.logout()
        except Exception:
            pass


def scan_inbox(host: str, username: str, password: str, port: int = 993, use_ssl: bool = True,
               mailbox: str = "INBOX", max_msgs: int = 20) -> List[Dict[str, Any]]:
    """
    Escanea la casilla IMAP y devuelve una lista de dicts:
      {uid, subject, from, date, attachments[], analysis{danger_level, reasons, iocs, hints?}}
    """
    results: List[Dict[str, Any]] = []
    with IMAPClient(host, port, use_ssl) as M:
        M.login(username, password)
        M.select(mailbox)

        # primero no leídos, si no, últimos N
        typ, data = M.search(None, '(UNSEEN)')
        ids = data[0].split()
        if not ids:
            typ, data = M.search(None, 'ALL')
            ids = data[0].split()[-max_msgs:]

        for uid in ids[-max_msgs:]:
            typ, msg_data = M.fetch(uid, '(RFC822)')
            if typ != 'OK' or not msg_data:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            subj = _decode_header(msg.get("Subject"))
            sender = _decode_header(msg.get("From"))
            date = msg.get("Date") or ""

            text, html, atts = _collect_parts(msg)
            analysis = _score_email(subj, sender, text, html, atts)

            results.append({
                "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
                "subject": subj,
                "from": sender,
                "date": date,
                "attachments": atts,
                "analysis": analysis
            })

    return results


# -------- Helper externo usado por /mail/scan (router “completo”) --------
def get_scan_summary(host: str, port: int, use_ssl: bool, username: str, password: str,
                     folder: str, mark_seen: bool, max_msgs: int = 50) -> Dict[str, Any]:
    """
    Conecta por IMAP y devuelve un resumen + items analizados (con iocs y hints).
    """
    imap = None
    try:
        imap = imaplib.IMAP4_SSL(host, port, timeout=30) if use_ssl else imaplib.IMAP4(host, port, timeout=30)
        typ, _ = imap.login(username, password)
        if typ != "OK":
            return {"ok": False, "login": False, "folder": folder, "unread": 0, "total": 0, "marked_seen": False,
                    "message": "Login IMAP falló", "items": []}

        typ, _ = imap.select(folder, readonly=not mark_seen)
        if typ != "OK":
            return {"ok": False, "login": True, "folder": folder, "unread": 0, "total": 0, "marked_seen": False,
                    "message": f"No se pudo abrir {folder}", "items": []}

        typ, data = imap.search(None, "ALL")
        total = len((data[0] or b"").split()) if typ == "OK" else 0
        typ, data = imap.search(None, "UNSEEN")
        unseen_ids = (data[0] or b"").split() if typ == "OK" else []
        unread = len(unseen_ids)

        # items con análisis completo
        items = scan_inbox(host, username, password, port, use_ssl, folder, max_msgs=max_msgs)

        try:
            imap.close(); imap.logout()
        except Exception:
            pass

        # resumen simple por niveles de severidad
        counts = {"low": 0, "medium": 0, "high": 0}
        dangerous = 0
        for it in items:
            lvl = (it.get("analysis", {}) or {}).get("danger_level", "low")
            counts[lvl] = counts.get(lvl, 0) + 1
            if lvl in ("medium", "high"):
                dangerous += 1

        return {
            "ok": True, "login": True, "folder": folder, "unread": unread, "total": total,
            "marked_seen": bool(mark_seen), "message": None, "items": items,
            "counts": counts, "dangerous": dangerous
        }
    except (imaplib.IMAP4.error) as e:
        return {"ok": False, "login": False, "folder": folder, "unread": 0, "total": 0,
                "marked_seen": False, "message": str(e), "items": []}
    except Exception as e:
        return {"ok": False, "login": False, "folder": folder, "unread": 0, "total": 0,
                "marked_seen": False, "message": f"Error: {e}", "items": []}

# --- Compat layer: scan_mailbox() ---
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

@dataclass
class MailAnalysis:
    risk_score: int = 0
    danger_level: str = ""
    reasons: List[str] = None
    iocs: Dict[str, Any] = None
    hints: Dict[str, Any] = None

    def __post_init__(self):
        self.reasons = self.reasons or []
        self.iocs = self.iocs or {}
        self.hints = self.hints or {}

@dataclass
class MailItem:
    uid: str = ""
    subject: str = ""
    from_email: str = ""
    date: str = ""
    attachments: List[str] = None
    analysis: MailAnalysis = None

    def __post_init__(self):
        self.attachments = self.attachments or []
        self.analysis = self.analysis or MailAnalysis()

@dataclass
class MailScanResult:
    ok: bool = False
    items: List[MailItem] = None
    total_found: int = 0
    unread: int = 0
    total: int = 0
    counts: Dict[str, Any] = None
    dangerous: int = 0
    message: Optional[str] = None

    def __post_init__(self):
        self.items = self.items or []
        self.counts = self.counts or {}

def scan_mailbox(
    host: str,
    port: int,
    username: str,
    password: str,
    folder: str = "INBOX",
    use_ssl: bool = True,
    limit: int = 20,
    mark_read: bool = False,
) -> MailScanResult:
    """
    Wrapper compatible con el router: devuelve un objeto con .items y .total_found.
    Internamente usa get_scan_summary() existente.
    """
    summary = get_scan_summary(
        host=host,
        username=username,
        password=password,
        port=port,
        use_ssl=use_ssl,
        folder=folder,
        max_msgs=int(limit),
        mark_seen=bool(mark_read),
    )

    raw_items = summary.get("items") or []
    items: List[MailItem] = []

    for it in raw_items:
        analysis = it.get("analysis") or {}
        items.append(
            MailItem(
                uid=str(it.get("uid") or it.get("id") or ""),
                subject=str(it.get("subject") or ""),
                from_email=str(it.get("from") or it.get("from_email") or ""),
                date=str(it.get("date") or ""),
                attachments=list(it.get("attachments") or []),
                analysis=MailAnalysis(
                    risk_score=int(analysis.get("risk_score") or analysis.get("score") or 0),
                    danger_level=str(analysis.get("danger_level") or ""),
                    reasons=list(analysis.get("reasons") or []),
                    iocs=dict(analysis.get("iocs") or {}),
                    hints=dict(analysis.get("hints") or {}),
                ),
            )
        )

    return MailScanResult(
        ok=bool(summary.get("ok")),
        items=items,
        total_found=len(items),
        unread=int(summary.get("unread") or 0),
        total=int(summary.get("total") or 0),
        counts=dict(summary.get("counts") or {}),
        dangerous=int(summary.get("dangerous") or 0),
        message=summary.get("message"),
    )
