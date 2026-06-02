# app/services/mail_scan.py
from __future__ import annotations

import socket
import logging
from dataclasses import dataclass
from typing import List, Dict, Any

from imapclient import IMAPClient
from email import message_from_bytes
from email.header import decode_header
from app.services.threat_rules import analyze_email_quick

log = logging.getLogger(__name__)

@dataclass
class MailScanItem:
    uid: str
    subject: str
    from_email: str
    date: str
    attachments: List[str]
    analysis: Any

@dataclass
class MailScanResult:
    ok: bool
    message: str
    total_found: int
    unread: int
    dangerous: int
    items: List[MailScanItem]
    counts: Dict[str, Any]

def _decode_mime_words(s: str) -> str:
    if not s: return ""
    try:
        parts = decode_header(s)
        out = ""
        for text, enc in parts:
            if isinstance(text, bytes):
                # Fallback seguro para encodings inventados por atacantes
                out += text.decode(enc or "utf-8", errors="replace")
            else:
                out += str(text)
        return out
    except Exception:
        return str(s)

def _extract_from(msg) -> str:
    return _decode_mime_words(msg.get("From", ""))

def _extract_subject(msg) -> str:
    return _decode_mime_words(msg.get("Subject", ""))

def _extract_date(msg) -> str:
    return (msg.get("Date", "") or "").strip()

def _safe_str(x) -> str:
    return str(x or "")

def _extract_attachments(msg) -> List[str]:
    out = []
    try:
        for part in msg.walk():
            cd = part.get("Content-Disposition", "") or ""
            if "attachment" in cd.lower():
                fn = part.get_filename()
                if fn: out.append(_decode_mime_words(fn))
    except Exception: pass
    return out

def _normalize_reasons(raw_reasons: Any) -> List[Any]:
    reasons = []
    for r in raw_reasons or []:
        if isinstance(r, dict): reasons.append(r)
        elif isinstance(r, str): reasons.append(r)
    return reasons

def scan_mailbox(
    host: str, port: int, username: str, password: str,
    folder: str = "INBOX", use_ssl: bool = True, limit: int = 50, mark_read: bool = False,
) -> MailScanResult:
    try:
        raw = scan_inbox(host=host, port=port, username=username, password=password, folder=folder, use_ssl=use_ssl, max_msgs=limit, mark_read=mark_read)
        if not raw.get("ok"):
            return MailScanResult(False, raw.get("message") or "scan failed", 0, 0, 0, [], {})

        items: List[MailScanItem] = []
        dangerous = 0
        counts = {"low": 0, "medium": 0, "high": 0}

        for it in raw.get("items", []) or []:
            # Combinamos el texto crudo y HTML eficientemente
            cuerpo_completo = (it.get("body", "") or "") + "\n\n" + (it.get("html", "") or "")
            
            analysis = analyze_email_quick(
                subject=it.get("subject", ""),
                sender=it.get("from", ""),
                body=cuerpo_completo,
            )

            lvl = (analysis.get("danger_level") or "low").lower()
            counts[lvl] = int(counts.get(lvl, 0)) + 1
            if lvl in ("medium", "high"): dangerous += 1

            analysis_dict = dict(analysis) if isinstance(analysis, dict) else analysis.__dict__.copy()
            analysis_dict["reasons"] = _normalize_reasons(analysis_dict.get("reasons"))
            
            items.append(MailScanItem(
                uid=_safe_str(it.get("uid")),
                subject=_safe_str(it.get("subject")),
                from_email=_safe_str(it.get("from")),
                date=_safe_str(it.get("date")),
                attachments=list(it.get("attachments") or []),
                analysis=type("A", (), analysis_dict)()
            ))

        return MailScanResult(True, "ok", len(items), int(raw.get("unread", 0)), dangerous, items, counts)

    except Exception as e:
        log.error(f"Error general en scan_mailbox: {e}")
        return MailScanResult(False, str(e), 0, 0, 0, [], {})

def scan_inbox(
    host: str, port: int, username: str, password: str,
    folder: str = "INBOX", use_ssl: bool = True, max_msgs: int = 50, mark_read: bool = False,
) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []

    try:
        # Timeout optimizado para no trabar la UI del cliente
        socket.setdefaulttimeout(15) 
        with IMAPClient(host, port=port, ssl=use_ssl) as M:
            M.login(username, password)
            M.select_folder(folder)

            uids = M.search(["ALL"]) or []
            uids = uids[-max_msgs:] if len(uids) > max_msgs else uids

            for uid in reversed(uids):
                try:
                    # BODY.PEEK evita marcar el mail como leído automáticamente en el servidor
                    data = M.fetch([uid], ["RFC822.HEADER", "BODY.PEEK[]", "FLAGS"])
                    raw = (data or {}).get(uid, {}).get(b"BODY[]") or (data or {}).get(uid, {}).get(b"RFC822")
                    if not raw: continue

                    msg = message_from_bytes(raw)
                    subject = _extract_subject(msg)
                    from_email = _extract_from(msg)
                    date = _extract_date(msg)
                    attachments = _extract_attachments(msg)

                    body_text, body_html = "", ""

                    if msg.is_multipart():
                        for part in msg.walk():
                            ctype = (part.get_content_type() or "").lower()
                            disp = (part.get("Content-Disposition", "") or "").lower()
                            
                            # IGNORAR ADJUNTOS PESADOS PARA NO COLGAR EL SCANNER
                            if "attachment" in disp or part.get_filename(): continue

                            payload = part.get_payload(decode=True)
                            if not payload: continue

                            charset = part.get_content_charset() or "utf-8"
                            if ctype == "text/plain" and not body_text:
                                body_text = payload.decode(charset, errors="replace")
                            elif ctype == "text/html" and not body_html:
                                body_html = payload.decode(charset, errors="replace")
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body_text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

                    if mark_read:
                        M.add_flags(uid, [b"\\Seen"])

                    items.append({
                        "uid": str(uid), "subject": subject, "from": from_email,
                        "date": date, "attachments": attachments,
                        "body": body_text, "html": body_html,
                    })
                except Exception as e_msg:
                    log.warning(f"Error parseando mensaje UID {uid}: {e_msg}")
                    continue # Salta el mail corrupto y sigue con el resto

            unread = 0
            try:
                unread = len(M.search(["UNSEEN"]) or [])
            except Exception: pass

            return {"ok": True, "message": "ok", "items": items, "unread": unread}

    except Exception as e:
        return {"ok": False, "message": str(e), "items": [], "unread": 0}
