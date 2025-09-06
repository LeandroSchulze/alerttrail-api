from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    plan = Column(String(20), default="FREE")  # FREE | PRO
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    analyses = relationship("Analysis", back_populates="user")

class Analysis(Base):
    __tablename__ = "analyses"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    source_name = Column(String(255), nullable=True)
    raw_log = Column(Text, nullable=False)
    result_summary = Column(Text, nullable=False)
    score_risk = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    pdf_path = Column(String(255), nullable=True)

    user = relationship("User", back_populates="analyses")

class UsageCounter(Base):
    __tablename__ = "usage_counters"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    date_key = Column(String(10), index=True)  # YYYY-MM-DD
    count = Column(Integer, default=0)
