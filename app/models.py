# app/models.py
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship

from app.database import Base


# =========================
# Users
# =========================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    # Identidad
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)

    # Password (compat)
    hashed_password = Column(String(512), nullable=True)   # pbkdf2$...
    password_hash   = Column(String(512), nullable=True)   # legacy/compat

    # Estado/roles/planes
    is_active     = Column(Boolean, nullable=False, default=True)
    role          = Column(String(20), nullable=False, default="user")   # user | admin
    plan          = Column(String(20), nullable=False, default="FREE")   # FREE | PRO | BIZ
    is_admin      = Column(Boolean, nullable=False, default=False)
    is_superuser  = Column(Boolean, nullable=False, default=False)

    # Organización a la que PERTENECE el usuario
    org_id        = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    is_org_admin  = Column(Boolean, nullable=False, default=False)

    # ================= Verificación por correo (nuevo) =================
    email_verified            = Column(Boolean, nullable=False, default=False)
    verification_code         = Column(String(12), nullable=True)             # p.ej. "123456"
    verification_expires_at   = Column(DateTime, nullable=True)               # vence en ~15 min
    verification_attempts     = Column(Integer, nullable=False, default=0)    # anti-bruteforce

    # Metadatos
    created_at    = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at    = Column(DateTime, nullable=True)

    # ---------------- Relaciones (desambiguadas) ----------------
    # Pertenece a UNA organización (vía users.org_id)
    organization = relationship(
        "Organization",
        foreign_keys=[org_id],
        back_populates="members",
        lazy="selectin",
    )

    # Es propietario (owner) de CERO o MÁS organizaciones (vía organizations.owner_user_id)
    owned_organizations = relationship(
        "Organization",
        foreign_keys="Organization.owner_user_id",
        back_populates="owner",
        lazy="selectin",
    )

    # Relación con otras tablas
    mail_accounts = relationship("MailAccount", back_populates="user", lazy="selectin")
    report_downloads = relationship("ReportDownload", back_populates="user", lazy="selectin")
    allowed_ips = relationship("AllowedIP", back_populates="user", lazy="selectin")
    accepted_invites = relationship("OrgInvite", back_populates="used_by_user", lazy="selectin")

    def __repr__(self):
        return (
            f"<User id={self.id} email={self.email!r} role={self.role} "
            f"plan={self.plan} email_verified={self.email_verified}>"
        )


# =========================
# Organizations
# =========================
class Organization(Base):
    __tablename__ = "organizations"

    id             = Column(Integer, primary_key=True, index=True)
    name           = Column(String(255), unique=True, nullable=False)

    # Dueño/propietario de la org
    owner_user_id  = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Licencias / facturación
    seats_total    = Column(Integer, nullable=False, default=1)
    seats_used     = Column(Integer, nullable=False, default=0)
    billing_id     = Column(String(255), nullable=True)

    created_at     = Column(DateTime, nullable=False, default=datetime.utcnow)

    # ---------------- Relaciones (desambiguadas) ----------------
    # Owner: va a User.owned_organizations
    owner = relationship(
        "User",
        foreign_keys=[owner_user_id],
        back_populates="owned_organizations",
        lazy="selectin",
    )

    # Miembros: vienen desde User.org_id
    members = relationship(
        "User",
        foreign_keys="User.org_id",
        back_populates="organization",
        lazy="selectin",
    )

    # Invites
    invites = relationship(
        "OrgInvite",
        foreign_keys="OrgInvite.org_id",
        back_populates="organization",
        lazy="selectin",
    )

    def __repr__(self):
        return f"<Organization id={self.id} name={self.name!r} owner_user_id={self.owner_user_id} seats={self.seats_used}/{self.seats_total}>"


# =========================
# Invitations to Organization
# =========================
class OrgInvite(Base):
    __tablename__ = "org_invites"

    id               = Column(Integer, primary_key=True, index=True)
    org_id           = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    email            = Column(String(255), nullable=True, index=True)   # destinatario
    token            = Column(String(64), nullable=True, unique=True)   # token público
    used             = Column(Boolean, nullable=False, default=False)
    used_by_user_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at       = Column(DateTime, nullable=False, default=datetime.utcnow)
    used_at          = Column(DateTime, nullable=True)

    # Relaciones (desambiguadas)
    organization = relationship(
        "Organization",
        foreign_keys=[org_id],
        back_populates="invites",
        lazy="selectin",
    )
    used_by_user = relationship(
        "User",
        foreign_keys=[used_by_user_id],
        back_populates="accepted_invites",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_org_invites_org_email", "org_id", "email"),
    )

    def __repr__(self):
        return f"<OrgInvite id={self.id} org_id={self.org_id} email={self.email!r} used={self.used}>"


# =========================
# Mail Accounts (IMAP)
# =========================
class MailAccount(Base):
    __tablename__ = "mail_accounts"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    email       = Column(String(255), nullable=False, index=True)

    # Conectividad IMAP
    imap_host   = Column(String(255), nullable=True)                    # legacy
    imap_server = Column(String(255), nullable=False, default="imap.gmail.com")
    imap_port   = Column(Integer, nullable=False, default=993)
    use_ssl     = Column(Boolean, nullable=False, default=True)

    # Credenciales/cifrado
    enc_password = Column(String(1024), nullable=True)                  # legacy
    enc_blob     = Column(Text, nullable=False, default="")             # preferido

    created_at  = Column(DateTime, nullable=True, default=datetime.utcnow)

    user = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="mail_accounts",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_mail_accounts_user_email", "user_id", "email"),
    )

    def __repr__(self):
        return f"<MailAccount id={self.id} user_id={self.user_id} email={self.email!r}>"


# =========================
# Report Downloads (PDFs, etc.)
# =========================
class ReportDownload(Base):
    __tablename__ = "report_downloads"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    path        = Column(String(1024), nullable=False)   # /reports/....pdf
    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="report_downloads",
        lazy="selectin",
    )

    def __repr__(self):
        return f"<ReportDownload id={self.id} user_id={self.user_id} path={self.path!r}>"


# =========================
# Allowed IPs (Opcional)
# =========================
class AllowedIP(Base):
    __tablename__ = "allowed_ips"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    ip_cidr     = Column(String(64), nullable=False)   # ej. "1.2.3.4/32"
    note        = Column(String(255), nullable=True)
    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="allowed_ips",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "ip_cidr", name="uq_allowed_ips_user_cidr"),
    )

    def __repr__(self):
        return f"<AllowedIP id={self.id} user_id={self.user_id} ip_cidr={self.ip_cidr!r}>"
