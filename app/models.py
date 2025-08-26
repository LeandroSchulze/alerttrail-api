# app/models.py
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from enum import Enum
from datetime import datetime
from .database import Base

class PlanEnum(str, Enum):
    FREE = "free"
    PRO = "pro"

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="User")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    plan: Mapped[PlanEnum] = mapped_column(SAEnum(PlanEnum), default=PlanEnum.FREE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    analyses: Mapped[list["Analysis"]] = relationship(back_populates="owner")

class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    title: Mapped[str] = mapped_column(String(255), default="Log Analysis")
    raw_log: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="")
    pdf_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    owner: Mapped["User"] = relationship(back_populates="analyses")

class DownloadMetric(Base):
    __tablename__ = "download_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    month_key: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    count: Mapped[int] = mapped_column(Integer, default=0)
Si querés hacerlo rápido en PowerShell (desde la carpeta del proyecto):

powershell
Copiar
Editar
@'
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from enum import Enum
from datetime import datetime
from .database import Base

class PlanEnum(str, Enum):
    FREE = "free"
    PRO = "pro"

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="User")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    plan: Mapped[PlanEnum] = mapped_column(SAEnum(PlanEnum), default=PlanEnum.FREE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    analyses: Mapped[list["Analysis"]] = relationship(back_populates="owner")

class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    title: Mapped[str] = mapped_column(String(255), default="Log Analysis")
    raw_log: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="")
    pdf_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    owner: Mapped["User"] = relationship(back_populates="analyses")

class DownloadMetric(Base):
    __tablename__ = "download_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    month_key: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    count: Mapped[int] = mapped_column(Integer, default=0)
'@ | Set-Content .\app\models.py -Encoding UTF8