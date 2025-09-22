# app/services/pro_alerts.py
import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from ..models_pro_alerts import ProAlertPref, ProAlertQueue, ProAlertState
from ..models_push import PushSubscription
from ..utils.push import send_web_push

DEFAULT_COOLDOWN = int(os.getenv("PRO_ALERTS_COOLDOWN_MIN", "10"))  # min

def _parse_quiet(quiet_str: str):
    if not quiet_str:
        return None
    try:
        a, b = quiet_str.split("-")
        return (int(a), int(b))
    except:
        return None

def _in_quiet_hours(now: datetime, quiet_tuple):
    if not quiet_tuple:
        return False
    start_h, end_h = quiet_tuple
    h = now.hour
    if start_h <= end_h:
        return start_h <= h < end_h
    return (h >= start_h) or (h < end_h)

def ensure_pref(db: Session, user_id: int) -> ProAlertPref:
    pref = db.query(ProAlertPref).filter_by(user_id=user_id).first()
    if not pref:
        pref = ProAlertPref(user_id=user_id, cooldown_min=DEFAULT_COOLDOWN, quiet_hours="", push_enabled=True)
        db.add(pref); db.commit()
    return pref

def _get_state(db: Session, user_id: int) -> ProAlertState:
    st = db.query(ProAlertState).filter_by(user_id=user_id).first()
    if not st:
        st = ProAlertState(user_id=user_id, last_push_at=None)
        db.add(st); db.commit()
    return st

def queue_or_push(db: Session, user, title: str, body: str, url: str="/dashboard") -> bool:
    if getattr(user, "plan", "").upper() != "PRO":
        return False

    pref = ensure_pref(db, user.id)
    if not pref.push_enabled:
        return False

    now = datetime.utcnow()
    quiet = _parse_quiet(pref.quiet_hours)
    st = _get_state(db, user.id)

    if _in_quiet_hours(now, quiet):
        db.add(ProAlertQueue(user_id=user.id, title=title, body=body, url=url))
        db.commit()
        return True

    if st.last_push_at and (now - st.last_push_at) < timedelta(minutes=pref.cooldown_min):
        db.add(ProAlertQueue(user_id=user.id, title=title, body=body, url=url))
        db.commit()
        return True

    _flush_grouped(db, user.id, immediate_extra=(title, body, url))
    return True

def _flush_grouped(db: Session, user_id: int, immediate_extra=None):
    rows = db.query(ProAlertQueue).filter_by(user_id=user_id).order_by(ProAlertQueue.created_at.asc()).all()
    items = [(r.title, r.body, r.url) for r in rows]
    if immediate_extra:
        items.append(immediate_extra)

    if not items:
        return False

    count = len(items)
    first_title, first_body, first_url = items[-1]
    summary = f"{count} detecciones nuevas" if count > 1 else first_body
    title = "AlertTrail PRO" if count > 1 else first_title
    url = first_url

    sub = db.query(PushSubscription).filter_by(user_id=user_id).first()
    if not sub:
        return False

    subscription = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
    payload = {"title": title, "body": summary, "url": url}
    ok = send_web_push(subscription, payload)
    if ok:
        for r in rows:
            db.delete(r)
        st = _get_state(db, user_id)
        st.last_push_at = datetime.utcnow()
        db.commit()
    return ok

def flush_if_needed(db: Session, user_id: int):
    pref = ensure_pref(db, user_id)
    quiet = _parse_quiet(pref.quiet_hours)
    now = datetime.utcnow()
    if not _in_quiet_hours(now, quiet):
        _flush_grouped(db, user_id)
