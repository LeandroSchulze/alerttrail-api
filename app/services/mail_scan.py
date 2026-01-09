# app/services/mail_scan.py
from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import List, Dict, Any

from imapclient import IMAPClient
from email import message_from_bytes
from email.header import decode_header

from app.services.threat_rules import analyze_email_quick


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
    if not s:
        return ""
    try:
        parts = decode_header(s)
        out = ""
        for text, enc in parts:
            if isinstance(text, bytes):
                out += text.decode(enc or "utf-8", errors="ignore")
            else:
                out += str(text)
        return out
    except Exception:
        return str(s)


def _extract_from(msg) -> str:
    try:
        return _decode_mime_words(msg.get("From", "") or "")
    except Exception:
        return ""


def _extract_subject(msg) -> str:
    try:
        return _decode_mime_words(msg.get("Subject", "") or "")
    except Exception:
        return ""


def _extract_date(msg) -> str:
    try:
        return (msg.get("Date", "") or "").strip()
    except Exception:
        return ""


def _safe_str(x) -> str:
    try:
        return str(x or "")
    except Exception:
        return ""


def _extract_attachments(msg) -> List[str]:
    out = []
    try:
        for part in msg.walk():
            cd = part.get("Content-Disposition", "") or ""
            if "attachment" in cd.lower():
                fn = part.get_filename()
                if fn:
                    out.append(_decode_mime_words(fn))
    except Exception:
        pass
    return out


def _normalize_reasons(raw_reasons: Any) -> List[Any]:
    """
    Convierte reasons legacy (strings) o mixtos a formato estructurado.
    No traduce, solo normaliza.
    """
    reasons: List[Any] = []

    for r in raw_reasons or []:
        if isinstance(r, dict):
            reasons.append(r)
        elif isinstance(r, str):
            # legacy → mantener string
            reasons.append(r)
    return reasons


def scan_mailbox(
    host: str,
    port: int,
    username: str,
    password: str,
    folder: str = "INBOX",
    use_ssl: bool = True,
    limit: int = 50,
    mark_read: bool = False,
) -> MailScanResult:
    try:
        raw = scan_inbox(
            host=host,
            port=port,
            username=username,
            password=password,
            folder=folder,
            use_ssl=use_ssl,
            max_msgs=limit,
            mark_read=mark_read,
        )
        if not raw.get("ok"):
            return MailScanResult(
                ok=False,
                message=raw.get("message") or "scan failed",
                total_found=0,
                unread=0,
                dangerous=0,
                items=[],
                counts={},
            )

        items: List[MailScanItem] = []
        dangerous = 0
        counts = {"low": 0, "medium": 0, "high": 0}

        for it in raw.get("items", []) or []:
            analysis = analyze_email_quick(
                subject=it.get("subject", ""),
                sender=it.get("from", ""),
                body=(it.get("body", "") or "")
                + (
                    "\n\n" + (it.get("html", "") or "")
                    if it.get("html")
                    else ""
                ),
            )

            lvl = (analysis.get("danger_level") or "low").lower()
            counts[lvl] = int(counts.get(lvl, 0)) + 1
            if lvl in ("medium", "high"):
                dangerous += 1

            # 🔑 Normalizar reasons (sin traducir)
            analysis["reasons"] = _normalize_reasons(
                analysis.get("reasons")
            )

            items.append(
                MailScanItem(
                    uid=_safe_str(it.get("uid")),
                    subject=_safe_str(it.get("subject")),
                    from_email=_safe_str(it.get("from")),
                    date=_safe_str(it.get("date")),
                    attachments=list(it.get("attachments") or []),
                    analysis=type("A", (), analysis)(),  # adapter obj-like
                )
            )

        return MailScanResult(
            ok=True,
            message="ok",
            total_found=len(items),
            unread=int(raw.get("unread", 0) or 0),
            dangerous=dangerous,
            items=items,
            counts=counts,
        )

    except Exception as e:
        return MailScanResult(
            ok=False,
            message=str(e),
            total_found=0,
            unread=0,
            dangerous=0,
            items=[],
            counts={},
        )


def scan_inbox(
    host: str,
    port: int,
    username: str,
    password: str,
    folder: str = "INBOX",
    use_ssl: bool = True,
    max_msgs: int = 50,
    mark_read: bool = False,
) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []

    try:
        socket.setdefaulttimeout(30)
        with IMAPClient(host, port=port, ssl=use_ssl) as M:
            M.login(username, password)
            M.select_folder(folder)

            uids = M.search(["ALL"]) or []
            uids = uids[-max_msgs:] if len(uids) > max_msgs else uids

            for uid in reversed(uids):
                data = M.fetch([uid], ["RFC822", "FLAGS"])
                raw = (data or {}).get(uid, {}).get(b"RFC822")

                if not raw:
                    continue

                msg = message_from_bytes(raw)

                subject = _extract_subject(msg)
                from_email = _extract_from(msg)
                date = _extract_date(msg)
                attachments = _extract_attachments(msg)

                body_text = ""
                body_html = ""

                try:
                    if msg.is_multipart():
                        for part in msg.walk():
                            ctype = (part.get_content_type() or "").lower()
                            disp = (part.get("Content-Disposition", "") or "").lower()
                            if "attachment" in disp:
                                continue

                            if ctype == "text/plain" and not body_text:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    body_text = payload.decode(
                                        part.get_content_charset() or "utf-8",
                                        errors="ignore",
                                    )
                            elif ctype == "text/html" and not body_html:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    body_html = payload.decode(
                                        part.get_content_charset() or "utf-8",
                                        errors="ignore",
                                    )
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body_text = payload.decode(
                                msg.get_content_charset() or "utf-8",
                                errors="ignore",
                            )
                except Exception:
                    pass

                try:
                    if mark_read:
                        M.add_flags(uid, [b"\\Seen"])
                except Exception:
                    pass

                items.append(
                    {
                        "uid": str(uid),
                        "subject": subject,
                        "from": from_email,
                        "date": date,
                        "attachments": attachments,
                        "body": body_text,
                        "html": body_html,
                    }
                )

            unread = 0
            try:
                unseen = M.search(["UNSEEN"]) or []
                unread = len(unseen)
            except Exception:
                unread = 0

            return {"ok": True, "message": "ok", "items": items, "unread": unread}

    except Exception as e:
        return {"ok": False, "message": str(e), "items": [], "unread": 0}
