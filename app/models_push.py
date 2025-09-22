# app/models_push.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from .database import Base

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    endpoint = Column(String, nullable=False)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint('user_id','endpoint', name='uq_user_endpoint'),)
app/models_pro_alerts.py
python
Copiar código
# app/models_pro_alerts.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from .database import Base

class ProAlertPref(Base):
    __tablename__ = "pro_alert_prefs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False, unique=True)
    cooldown_min = Column(Integer, default=10, nullable=False)  # minutos
    quiet_hours = Column(String, default="", nullable=False)    # ej "23-07" o ""
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
