from sqlalchemy import Column, Integer, String, ForeignKey, JSON, DateTime
from sqlalchemy.sql import func
from app.database import Base

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    endpoint = Column(String, unique=True, nullable=False)
    subscription = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
