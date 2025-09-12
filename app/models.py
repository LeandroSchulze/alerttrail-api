from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    plan = Column(String, default="free")  # "free" o "pro" (admin)
    is_active = Column(Boolean, default=True)
    trial_ends_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
