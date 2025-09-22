# app/models_pro_alerts.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from .database import Base

class ProAlertPref(Base):
    __tablename__ = "pro_alert_prefs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False, unique=True)
    cooldown_min = Column(Integer, default=10, nullable=False)
    quiet_hours = Column(String, default="", nullable=False)
    push_enabled = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class ProAlertQueue(Base):
    __tablename__ = "pro_alert_queue"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    url = Column(String, default="/dashboard", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class ProAlertState(Base):
    __tablename__ = "pro_alert_state"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True, nullable=False, unique=True)
    last_push_at = Column(DateTime, nullable=True)
