# app/models.py
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    LargeBinary,
)
from sqlalchemy.orm import relationship

from app.database import Base


# ---------------------------
# Usuario
# ---------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)  # bcrypt hash
    plan = Column(String(20), nullable=False, default="free")  # "free" | "pro"
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relación opcional con descargas de reportes (si el router admin la usa)
    report_downloads = relationship(
        "ReportDownload",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ---------------------------
# Lista blanca de IPs (admin)
# ---------------------------
class AllowedIP(Base):
    __tablename__ = "allowed_ips"

    id = Column(Integer, primary_key=True, index=True)
    ip = Column(String(64), unique=True, nullable=False)
    note = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------
# Descargas de reportes (admin / billing)
# ---------------------------------------
class ReportDownload(Base):
    __tablename__ = "report_downloads"

    id = Column(Integer, primary_key=True)

    # Si el reporte está asociado a un usuario; SET NULL para conservar registros
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    user = relationship("User", back_populates="report_downloads")

    # Metadatos
    filename = Column(String(255), nullable=False)               # ej. "reporte.pdf"
    mime = Column(String(100), default="application/pdf")
    size_bytes = Column(Integer, default=0)

    # Almacenamiento: usá UNO u OTRO según tu implementación
    data = Column(LargeBinary, nullable=True)                    # PDF en la DB (opcional)
    storage_path = Column(String(512), nullable=True)            # Ruta en disco/obj storage (opcional)

    # Opcionales útiles (links temporales, flags)
    token = Column(String(64), unique=True, nullable=True)
    ready = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
