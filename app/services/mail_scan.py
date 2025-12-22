# app/services/mail_scan.py
from __future__ import annotations

import email
import re
import ssl
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import Message
from typing import Any, Dict, List, Optional

import imaplib


# -----------------------------
# Data models (compat)
# -----------------------------
@dataclass
class MailAnalysis:
    risk_score: int
    danger_level: str
    reasons: List[str]
    iocs: Dict[str, Any]
    hints: Dict[str, Any]


@dataclass
class MailItem:
    uid: str
    from_email: str
    subject: str
    date: str
    attachments: List[Dict[str, Any]]
    analysis: MailAnalysis


@dataclass
class MailScanResult:
    ok: bool
    items: List[MailItem]
    total_found: int
    unread: int
    total: int
    counts: Dict[str, Any]
    dangerous: int
    message: Optional[str] = None


# -----------------------------
# Helpers
# -----------------------------
_URL_RE = re.compile(r"https?://[^\s<>\"]+", re.I)
_PUNYCODE_RE = re.compile(r"\bxn--[a-z0-9\-]+\b", re.I)
_OTP_RE = re.compile(r"\b(otp|one[- ]time|c[oó]digo|code)\b", re.I)
_URGENT_RE = re.compile(r"\b(urgente|urgent|suspend|bloque|verify|verific|security|seguridad)\b", re.I)
_QR_RE = re.compile(r"\b(qr)\b", re.I)

_BAD_EXT = (".exe", ".js", ".vbs", ".bat", ".cmd", ".scr", ".msi", ".iso", ".img", ".zip", ".rar", ".7z")


def _decode_header(val: str) -> str:
    if not val:
        return ""
    try:
        return str(make_header(decode_header(val)))
    except Exception:
        return val


def _extract_text_parts(msg: Message) -> Dict[str, str]:
    text = ""
    html = ""

    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue

            try:
                payload = part.get_payload(decode=True)
            except Exception:
                payload = None

            charset = (part.get_content_charset() or "utf-8") if hasattr(part, "get_content_charset") else "utf-8"
            if payload:
                try:
                    decoded = payload.decode(charset, errors="ignore")
                except Exception:
                    decoded = payload.decode("utf-8", errors="ignore")

                if ctype == "text/plain":
                    text += decoded + "\n"
                elif ctype == "text/html":
                    html += decoded + "\n"
    else:
        ctype = (msg.get_content_type() or "").lower()
        payload = msg.get_payload(decode=True) or b""
        charset = (msg.get_content_charset() or "utf-8")
        try:
            decoded = payload.decode(charset, errors="ignore")
        except Exception:
            decoded = payload.decode("utf-8", errors="ignore")
        if ctype == "text/html":
            html = decoded
        else:
            text = decoded

    return {"text": text.strip(), "html": html.strip()}


def _extract_attachments(msg: Message) -> List[Dict[str, Any]]:
    atts: List[Dict[str, Any]] = []
    if not msg.is_multipart():
        return atts

    for part in msg.walk():
        disp = (part.get("Content-Disposition") or "").lower()
        if "attachment" not in disp:
            continue

        filename = part.get_filename() or ""
        filename = _decode_header(filename)
        size = 0
        try:
            payload = part.get_payload(decode=True) or b""
            size = len(payload)
        except Exception:
            pass

        atts.append({"filename": filename, "size": size})
    return atts


def _score_email(subject: str, sender: str, text: str, html: str,
                 atts: List[Dict[str, Any]]) -> Dict[str, Any]:
    danger = 0
    reasons: List[str] = []
    iocs: Dict[str, Any] = {}
    hints: Dict[str, Any] = {}

    subj_l = (subject or "").lower()
    sender_l = (sender or "").lower()
    blob = (text or "") + "\n" + (html or "")

    urls = _URL_RE.findall(blob)
    if urls:
        iocs["urls"] = urls[:10]

    if _URGENT_RE.search(subj_l) or _URGENT_RE.search(blob.lower()):
        danger += 2
        reasons.append("Urgencia / presión para actuar")

    if _OTP_RE.search(blob.lower()):
        danger += 2
        reasons.append("Menciona códigos / OTP (posible takeover)")

    if _PUNYCODE_RE.search(blob.lower()):
        danger += 2
        reasons.append("Dominio punycode (IDN) detectado")

    if urls and any(_PUNYCODE_RE.search(u) for u in urls):
        danger += 2
        reasons.append("URL con punycode detectado")

    if _QR_RE.search(blob.lower()):
        danger += 1
        reasons.append("Posible intento de QR-phishing")

    if "no-reply" in sender_l and ("verify" in blob.lower() or "verific" in blob.lower()):
        danger += 1
        reasons.append("Patrones típicos de phishing (no-reply + verify)")

    # Adjuntos peligrosos
    bad_att = []
    for a in atts or []:
        fn = (a.get("filename") or "").lower()
        if any(fn.endswith(ext) for ext in _BAD_EXT):
            bad_att.append(a.get("filename") or "")
    if bad_att:
        danger += 3
        reasons.append("Adjunto potencialmente peligroso")
        iocs["dangerous_attachments"] = bad_att

    # Clasificación
    if danger >= 5:
        level = "high"
    elif danger >= 2:
        level = "medium"
    else:
        level = "low"

    # Score (para logs/alertas), aunque no lo muestres en UI
    if level == "high":
        risk_score = min(100, 80 + danger * 4)
    elif level == "medium":
        risk_score = min(100, 45 + danger * 6)
    else:
        risk_score = min(35, 10 + danger * 8)

    return {
        "danger_level": level,
        "risk_score": int(risk_score),
        "reasons": reasons,
        "iocs": iocs,
        "hints": hints,
    }


# -----------------------------
# IMAP minimal client
# -----------------------------
class IMAPClient:
    def __init__(self, host: str, port: int, use_ssl: bool):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.conn: Optional[imaplib.IMAP4] = None

    def __enter__(self):
        if self.use_ssl:
            ctx = ssl.create_default_context()
            self.conn = imaplib.IMAP4_SSL(self.host, self.port, ssl_context=ctx)
        else:
            self.conn = imaplib.IMAP4(self.host, self.port)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.conn:
                self.conn.logout()
        except Exception:
            pass

    def login(self, username: str, password: str):
        assert self.conn is not None
        self.conn.login(username, password)

    def select(self, mailbox: str):
        assert self.conn is not None
        self.conn.select(mailbox)

    def uid_search(self, criteria: str):
        assert self.conn is not None
        typ, data = self.conn.uid("search", None, criteria)
        if typ != "OK":
            return []
        raw = data[0] if data else b""
        if not raw:
            return []
        return raw.split()

    def uid_fetch(self, uid: bytes, parts: str):
        assert self.conn is not None
        typ, data = self.conn.uid("fetch", uid, parts)
        if typ != "OK":
            return None
        return data


def scan_inbox(host: str, username: str, password: str, port: int = 993, use_ssl: bool = True,
               mailbox: str = "INBOX", max_msgs: int = 20) -> List[Dict[str, Any]]:
    """
    Devuelve lista de dicts con: uid, from, subject, date, body(text/html), attachments, analysis
    """
    out: List[Dict[str, Any]] = []

    with IMAPClient(host, port, use_ssl) as M:
        M.login(username, password)
        M.select(mailbox)

        # Primero UNSEEN (si hay), sino ALL (últimos N por UID)
        uids = M.uid_search("(UNSEEN)")
        if not uids:
            uids = M.uid_search("ALL")

        # Tomamos últimos N por UID (lo más nuevo)
        uids = uids[-max_msgs:] if len(uids) > max_msgs else uids

        for uid in uids:
            fetched = M.uid_fetch(uid, "(RFC822)")
            if not fetched:
                continue

            raw_msg = None
            for part in fetched:
                if isinstance(part, tuple) and part[1]:
                    raw_msg = part[1]
                    break
            if not raw_msg:
                continue

            msg = email.message_from_bytes(raw_msg)
            subj = _decode_header(msg.get("Subject", ""))
            frm = _decode_header(msg.get("From", ""))
            date = _decode_header(msg.get("Date", ""))

            parts = _extract_text_parts(msg)
            atts = _extract_attachments(msg)

            analysis = _score_email(subj, frm, parts["text"], parts["html"], atts)

            out.append(
                {
                    "uid": uid.decode(errors="ignore"),
                    "from": frm,
                    "subject": subj,
                    "date": date,
                    "text": parts["text"],
                    "html": parts["html"],
                    "attachments": atts,
                    "analysis": analysis,
                }
            )

    return out


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
    items_raw = scan_inbox(
        host=host,
        port=port,
        username=username,
        password=password,
        use_ssl=use_ssl,
        mailbox=folder,
        max_msgs=limit,
    )

    items: List[MailItem] = []
    for it in items_raw:
        analysis = it.get("analysis") or {}
        items.append(
            MailItem(
                uid=str(it.get("uid") or ""),
                from_email=str(it.get("from") or ""),
                subject=str(it.get("subject") or ""),
                date=str(it.get("date") or ""),
                attachments=list(it.get("attachments") or []),
                analysis=MailAnalysis(
                    risk_score=int(analysis.get("risk_score") or 0),
                    danger_level=str(analysis.get("danger_level") or ""),
                    reasons=list(analysis.get("reasons") or []),
                    iocs=dict(analysis.get("iocs") or {}),
                    hints=dict(analysis.get("hints") or {}),
                ),
            )
        )

    return MailScanResult(
        ok=True,
        items=items,
        total_found=len(items),
        unread=0,
        total=len(items),
        counts={},
        dangerous=sum(1 for i in items if (i.analysis.danger_level or "") in ("medium", "high")),
        message=None,
    )
