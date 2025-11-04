# app/services/mail_scan.py
import imaplib, email, re, os
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

URL_RE = re.compile(r"https?://[^\s\"'>)]+", re.I)
OTP_RE = re.compile(r"\b(\d{6})\b")

# dominios y TLDs sospechosos
SUSP_TLDS = (".zip", ".mov")


# ---------------- Utilidades ----------------
def _decode_header(val: Any) -> str:
    try:
        return str(make_header(decode_header(val))) if val else ""
    except Exception:
        return str(val or "")


def _get_filename(part) -> str:
    filename = part.get_filename()
    return _decode_header(filename)


def _strip_html(html: str) -> str:
    # quita tags simples para generar un snippet legible
    txt = re.sub(r"<(script|style)[\s\S]*?</\1>", "", html, flags=re.I)
    txt = re.sub(r"<br\s*/?>", "\n", txt, flags=re.I)
    txt = re.sub(r"</p\s*>", "\n", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


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
      score: 0..1 (heurístico)
    """
    reasons: List[str] = []
    iocs: Dict[str, Any] = {"urls": [], "otp_codes": []}
    danger = 0

    # URLs
    all_text = " ".join([subject or "", sender or "", text or "", html or ""])
    urls = URL_RE.findall(all_text)
    iocs["urls"] = urls
    if any(u.lower().endswith(SUSP_TLDS) for u in urls):
        reasons.append("URLs con TLDs sospechosos (.zip/.mov)")
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

    # Clasificación de riesgo
    if danger >= 4:
        level = "high"
    elif danger >= 2:
        level = "medium"
    else:
        level = "low"

    # score 0..1 proporcional al "danger"
    score = min(1.0, danger / 6.0)

    return {"danger_level": level, "reasons": reasons, "iocs": iocs, "score": score}


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
      {uid, subject, from, date, attachments[], analysis{danger_level, reasons, iocs, score}, snippet, suspicious}
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
            snippet_source = text or _strip_html(html)
            snippet = (snippet_source or "").strip().replace("\r", " ").replace("\n", " ")
            snippet = snippet[:260]

            analysis = _score_email(subj, sender, text, html, atts)
            suspicious = analysis.get("danger_level") in {"medium", "high"}

            results.append({
                "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
                "subject": subj,
                "from": sender,
                "date": date,
                "attachments": atts,
                "snippet": snippet,
                "suspicious": suspicious,
                "score": analysis.get("score", 0.0),
                "analysis": analysis
            })

    return results


# --- Utilidad opcional para el endpoint /mail/scan basado en ENV (no rompe nada existente)
def scan_env(max_msgs: int = 20) -> Dict[str, Any]:
    """
    Usa las variables de entorno MAIL_* y devuelve el payload completo
    esperado por /mail/scan (ok, totals e items).
    """
    host = os.getenv("MAIL_HOST", "imap.gmail.com")
    port = int(os.getenv("MAIL_PORT", "993") or 993)
    use_ssl = str(os.getenv("MAIL_USE_SSL", "true")).strip().lower() in {"1","true","yes","on"}
    username = os.getenv("MAIL_USERNAME", "")
    password = os.getenv("MAIL_PASSWORD", "")
    folder = os.getenv("MAIL_FOLDER", "INBOX") or "INBOX"

    if not username or not password:
        return {"ok": False, "login": False, "folder": folder, "unread": 0, "total": 0,
                "marked_seen": False, "message": "Faltan MAIL_USERNAME o MAIL_PASSWORD", "items": []}

    try:
        with IMAPClient(host, port, use_ssl) as M:
            M.login(username, password)
            M.select(folder)

            typ, data_all = M.search(None, "ALL")
            total = len((data_all[0] or b"").split()) if typ == "OK" else 0

            typ, data_unseen = M.search(None, "UNSEEN")
            unread = len((data_unseen[0] or b"").split()) if typ == "OK" else 0

        items = scan_inbox(host, username, password, port, use_ssl, folder, max_msgs=max_msgs)
        return {"ok": True, "login": True, "folder": folder, "unread": unread, "total": total,
                "marked_seen": False, "message": None, "items": items}
    except imaplib.IMAP4.error as e:
        return {"ok": False, "login": False, "folder": folder, "unread": 0, "total": 0,
                "marked_seen": False, "message": f"IMAP error: {e}", "items": []}
    except Exception as e:
        return {"ok": False, "login": False, "folder": folder, "unread": 0, "total": 0,
                "marked_seen": False, "message": f"Error: {e}", "items": []}
