# app/routers/mail.py
@router.get("/scan")
def scan_get(request: Request, user=Depends(get_current_user_cookie_optional), db: Session = Depends(get_db), limit: int = Query(20)):
    if not user: return RedirectResponse(url="/auth/login", status_code=302)
    uid = _extract_uid(user)
    
    acc = db.query(MailAccount).filter(MailAccount.user_id == uid).first() if uid else None
    if not acc or not acc.password_encrypted: return RedirectResponse(url="/mail/scanner?error=no_linked", status_code=303)

    res = scan_mailbox(host=acc.host, port=acc.port or 993, username=acc.username or acc.email, password=acc.password_encrypted, folder="INBOX", use_ssl=acc.use_ssl, limit=limit)

    items = []
    has_high_threat = False
    verdict_map = {
        "ALTA": "alerts.severity_high",
        "MEDIA": "alerts.severity_medium",
        "BAJA": "alerts.severity_low"
    }

    for it in (res.items or []):
        raw_reasons = getattr(it.analysis, "reasons", [])
        subject = str(it.subject).lower()
        reasons_flat = str(raw_reasons).lower()
        
        score = 0
        if "links_count" in reasons_flat and "20" in reasons_flat: score += 20
        if "phishing" in reasons_flat: score += 10
        if any(w in subject for w in ["alerta", "urgente", "bloqueo", "confirm"]): score += 10
            
        if score >= 15:
            final_lvl = "ALTA"
            has_high_threat = True
        elif score >= 8:
            final_lvl = "MEDIA"
        else:
            final_lvl = "BAJA"

        items.append({
            "uid": str(it.uid), 
            "subject": str(it.subject), 
            "from": str(it.from_email), 
            "date": str(it.date), 
            "date_ts": _parse_date_ts(str(it.date)), 
            "verdict": final_lvl,
            "verdict_key": verdict_map[final_lvl], # <--- FIX: Clave que espera el HTML
            "reasons": raw_reasons # <--- FIX: No convertir a str para que el template use sus iconos/traducciones
        })
    
    items.sort(key=lambda x: x["date_ts"], reverse=True)
    _save_json(_scan_file_for(user), {"ok": res.ok, "scanned_at": _now_iso(), "items": items, "total": res.total_found})

    if has_high_threat and uid:
        trigger_push_notification(user_id=uid, title="🚨 ALERTA CRÍTICA", body="Se detectó un intento de hackeo.")

    return RedirectResponse(url="/mail/scanner?scanned=1", status_code=303)
