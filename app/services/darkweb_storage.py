# app/services/darkweb_storage.py
"""
Almacenamiento simple en JSON para Dark Web Radar.
No toca la base de datos; guarda todo en /var/data/darkweb_watch.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_PATH = Path(os.getenv("DARKWEB_DATA_PATH", "/var/data/darkweb_watch.json"))


def _load() -> Dict[str, Any]:
    if not DATA_PATH.exists():
        return {"emails": [], "exposures": []}
    try:
        return json.loads(DATA_PATH.read_text("utf-8"))
    except Exception:
        return {"emails": [], "exposures": []}


def _save(data: Dict[str, Any]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def list_emails(owner_id: int) -> List[Dict[str, Any]]:
    data = _load()
    emails = [e for e in data.get("emails", []) if e.get("owner_id") == owner_id]
    emails.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
    return emails


def add_email(owner_id: int, email: str) -> None:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return

    data = _load()
    emails = data.setdefault("emails", [])
    for e in emails:
        if e.get("owner_id") == owner_id and e.get("email") == email:
            return  # ya existe

    now = int(time.time())
    emails.append(
        {
            "owner_id": owner_id,
            "email": email,
            "created_at": now,
        }
    )
    _save(data)


def remove_email(owner_id: int, email: str) -> None:
    email = (email or "").strip().lower()
    data = _load()
    emails = data.get("emails", [])
    emails = [
        e
        for e in emails
        if not (e.get("owner_id") == owner_id and e.get("email") == email)
    ]
    data["emails"] = emails
    _save(data)


def list_exposures(owner_id: int) -> List[Dict[str, Any]]:
    data = _load()
    exps = [x for x in data.get("exposures", []) if x.get("owner_id") == owner_id]
    exps.sort(
        key=lambda x: x.get("breach_date") or x.get("created_at") or 0, reverse=True
    )
    return exps


def mark_exposure_seen(owner_id: int, exposure_id: str) -> None:
    data = _load()
    exps = data.get("exposures", [])
    changed = False
    for e in exps:
        if e.get("owner_id") == owner_id and str(e.get("id")) == str(exposure_id):
            if e.get("status") != "seen":
                e["status"] = "seen"
                changed = True
    if changed:
        data["exposures"] = exps
        _save(data)


def _add_exposure_record(
    data: Dict[str, Any],
    owner_id: int,
    email: str,
    breach: str,
    severity: str,
    summary: str,
    breach_date: Optional[int] = None,
) -> None:
    exps = data.setdefault("exposures", [])
    # Evitar duplicados por (owner_id, email, breach)
    for e in exps:
        if (
            e.get("owner_id") == owner_id
            and e.get("email") == email
            and e.get("breach") == breach
        ):
            return

    now = int(time.time())
    rec = {
        "id": f"{owner_id}-{now}-{len(exps)+1}",
        "owner_id": owner_id,
        "email": email,
        "breach": breach,
        "severity": severity,
        "summary": summary,
        "breach_date": breach_date or now,
        "status": "new",
        "created_at": now,
    }
    exps.append(rec)


def simulate_scan_for_owner(owner_id: int) -> int:
    """
    Simulación de scan de fugas.
    NO consulta nada real todavía: genera ejemplos para que el panel tenga datos.
    Es seguro y no rompe nada si no se usa.
    """
    data = _load()
    emails = [e for e in data.get("emails", []) if e.get("owner_id") == owner_id]
    if not emails:
        return 0

    before = len(data.get("exposures", []))

    for e in emails:
        email = e.get("email") or ""
        if "@gmail.com" in email:
            _add_exposure_record(
                data,
                owner_id,
                email,
                "Servicio popular (fuga simulada)",
                "medium",
                "Ejemplo de credenciales expuestas en un servicio popular (simulado).",
            )
        elif any(x in email for x in ("@outlook.", "@hotmail.", "@live.")):
            _add_exposure_record(
                data,
                owner_id,
                email,
                "Brecha antigua (simulada)",
                "low",
                "Registro simulado de una brecha antigua con bajo impacto.",
            )
        else:
            # Dominio corporativo
            domain = email.split("@", 1)[-1]
            _add_exposure_record(
                data,
                owner_id,
                email,
                f"Posible fuga en {domain} (simulada)",
                "high",
                "Entrada simulada para probar Dark Web Radar sobre un dominio corporativo.",
            )

    _save(data)
    after = len(data.get("exposures", []))
    return max(after - before, 0)
