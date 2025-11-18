# app/services/training_storage.py
"""
Almacenamiento JSON para Phishing Training (recipients + campaigns).
No modifica la base de datos.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

DATA_PATH = Path(os.getenv("TRAINING_DATA_PATH", "/var/data/training_data.json"))


def _load() -> Dict[str, Any]:
    if not DATA_PATH.exists():
        return {"recipients": [], "campaigns": []}
    try:
        return json.loads(DATA_PATH.read_text("utf-8"))
    except Exception:
        return {"recipients": [], "campaigns": []}


def _save(data: Dict[str, Any]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def list_recipients(owner_id: int) -> List[Dict[str, Any]]:
    data = _load()
    recs = [r for r in data.get("recipients", []) if r.get("owner_id") == owner_id]
    recs.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
    return recs


def add_recipient(owner_id: int, email: str, name: str = "") -> None:
    email = (email or "").strip().lower()
    name = (name or "").strip()
    if not email or "@" not in email:
        return

    data = _load()
    recs = data.setdefault("recipients", [])
    for r in recs:
        if r.get("owner_id") == owner_id and r.get("email") == email:
            # actualizar nombre si viene vacío antes
            if name and not r.get("name"):
                r["name"] = name
                _save(data)
            return

    now = int(time.time())
    recs.append(
        {
            "id": f"r-{owner_id}-{now}-{len(recs)+1}",
            "owner_id": owner_id,
            "email": email,
            "name": name,
            "created_at": now,
        }
    )
    _save(data)


def delete_recipient(owner_id: int, email: str) -> None:
    email = (email or "").strip().lower()
    data = _load()
    recs = data.get("recipients", [])
    recs = [
        r
        for r in recs
        if not (r.get("owner_id") == owner_id and r.get("email") == email)
    ]
    data["recipients"] = recs
    _save(data)


def list_campaigns(owner_id: int) -> List[Dict[str, Any]]:
    data = _load()
    camps = [c for c in data.get("campaigns", []) if c.get("owner_id") == owner_id]
    camps.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
    return camps


def create_campaign(
    owner_id: int,
    name: str,
    template_id: str,
    recipient_emails: List[str],
) -> Dict[str, Any]:
    name = (name or "").strip()
    template_id = (template_id or "").strip()
    normalized_emails = sorted({(e or "").strip().lower() for e in recipient_emails if e})
    data = _load()
    camps = data.setdefault("campaigns", [])

    now = int(time.time())
    camp = {
        "id": f"c-{owner_id}-{now}-{len(camps)+1}",
        "owner_id": owner_id,
        "name": name or f"Campaña {time.strftime('%Y-%m-%d', time.localtime(now))}",
        "template_id": template_id or "password_reset",
        "recipient_emails": normalized_emails,
        "status": "created",  # created | sent (simulado)
        "created_at": now,
        "sent_at": None,
    }
    camps.append(camp)
    _save(data)
    return camp


def mark_campaign_sent(owner_id: int, campaign_id: str) -> None:
    data = _load()
    camps = data.get("campaigns", [])
    changed = False
    for c in camps:
        if c.get("owner_id") == owner_id and str(c.get("id")) == str(campaign_id):
            if c.get("status") != "sent":
                c["status"] = "sent"
                c["sent_at"] = int(time.time())
                changed = True
    if changed:
        data["campaigns"] = camps
        _save(data)
