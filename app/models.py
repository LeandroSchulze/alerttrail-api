from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
#                              -----------------^^^^^^^
from datetime import datetime
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    # Plan del usuario (FREE/PRO)
    plan = Column(String, default="FREE", nullable=False)

    # Nuevo: estado activo
    is_active = Column(Boolean, default=True, nullable=False)

# --- AllowedIP (usado por router admin) -------------------------------------
class AllowedIP(Base):
    __tablename__ = "allowed_ips"

    id = Column(Integer, primary_key=True, index=True)
    ip = Column(String(64), unique=True, nullable=False)
    note = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
