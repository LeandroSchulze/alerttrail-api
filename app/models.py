# app/models.py
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Index, UniqueConstraint, Numeric
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

    # Organización
    org_id        = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    is_org_admin  = Column(Boolean, nullable=False, default=False)

    # Verificación por correo
    email_verified            = Column(Boolean, nullable=False, default=False)
    verification_code         = Column(String(12), nullable=True)
    verification_expires_at   = Column(DateTime, nullable=True)
    verification_attempts     = Column(Integer, nullable=False, default=0)
    last_verification_sent_at = Column(DateTime, nullable=True)

    # Recuperación de contraseña
    reset_code          = Column(String(64), nullable=True)
    reset_code_sent_at  = Column(DateTime, nullable=True)
    reset_code_used_at  = Column(DateTime, nullable=True)

    # Plan PRO / trial
    pro_started_at  = Column(DateTime, nullable=True)
    pro_expires_at  = Column(DateTime, nullable=True)
    trial_started_at = Column(DateTime, nullable=True)
    trial_expires_at = Column(DateTime, nullable=True)
    trial_used       = Column(Boolean, nullable=False, default=False)

    # Auditoría básica
    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at  = Column(DateTime, nullable=True)

    # Relaciones
    organization = relationship(
        "Organization",
        foreign_keys=[org_id],
        back_populates="members",
        lazy="selectin",
    )
    owned_organizations = relationship(
        "Organization",
        foreign_keys="Organization.owner_user_id",
        back_populates="owner",
        lazy="selectin",
    )
    mail_accounts = relationship("MailAccount", back_populates="user", lazy="selectin")
    report_downloads = relationship("ReportDownload", back_populates="user", lazy="selectin")
    allowed_ips = relationship("AllowedIP", back_populates="user", lazy="selectin")
    accepted_invites = relationship(
        "OrgInvite",
        back_populates="used_by_user",
        foreign_keys="OrgInvite.used_by_user_id",
        lazy="selectin",
    )

    # Pagos
    payment_events = relationship("PaymentEvent", back_populates="user", lazy="selectin")
    payments       = relationship("PaymentHistory", back_populates="user", lazy="selectin")
    darkweb_requests = relationship("DarkwebScanRequest", back_populates="user", lazy="selectin")

    # Helpers
    @property
    def is_pro_active(self) -> bool:
        now = datetime.utcnow()
        if self.plan and self.plan.upper() in ("PRO", "BIZ"):
            if self.pro_expires_at:
                return self.pro_expires_at > now
            # Si no hay fecha de expiración, consideramos PRO activo
            return True
        return False

    def pro_days_left(self) -> Optional[int]:
        if not self.pro_expires_at:
            return None
        delta = self.pro_expires_at - datetime.utcnow()
        return max(delta.days, 0)

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
    owner_user_id  = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    seats_total    = Column(Integer, nullable=False, default=1)
    seats_used     = Column(Integer, nullable=False, default=1)

    # Plan / billing
    plan           = Column(String(32), nullable=False, default="BIZ")   # BIZ / EMPRESA / etc
    stripe_customer_id = Column(String(128), nullable=True)
    mp_preapproval_id  = Column(String(128), nullable=True)

    # Auditoría
    created_at     = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at     = Column(DateTime, nullable=True)

    # Relaciones
    owner   = relationship("User", foreign_keys=[owner_user_id], back_populates="owned_organizations")
    members = relationship("User", back_populates="organization", lazy="selectin")
    invitations = relationship("OrgInvite", back_populates="organization", lazy="selectin")

    def __repr__(self):
        return f"<Organization id={self.id} name={self.name!r} plan={self.plan}>"


# =========================
# Organization Invites
# =========================
class OrgInvite(Base):
    __tablename__ = "org_invites"

    id              = Column(Integer, primary_key=True, index=True)
    org_id          = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    email           = Column(String(255), nullable=False)
    token           = Column(String(64), unique=True, nullable=False)
    invited_by_id   = Column(Integer, ForeignKey("users.id"), nullable=True)
    used_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    accepted_at     = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at      = Column(DateTime, nullable=True)

    organization    = relationship("Organization", back_populates="invitations", lazy="selectin")
    invited_by      = relationship("User", foreign_keys=[invited_by_id], lazy="selectin")
    used_by_user    = relationship("User", foreign_keys=[used_by_user_id], back_populates="accepted_invites", lazy="selectin")

    __table_args__ = (
        Index("ix_org_invites_org_email", "org_id", "email"),
        Index("ix_org_invites_token", "token"),
    )

    def __repr__(self):
        return f"<OrgInvite id={self.id} org_id={self.org_id} email={self.email!r}>"


# =========================
# Mail Accounts
# =========================
class MailAccount(Base):
    __tablename__ = "mail_accounts"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    email       = Column(String(255), nullable=False)
    provider    = Column(String(32), nullable=False, default="imap")
    host        = Column(String(255), nullable=False)
    port        = Column(Integer, nullable=False, default=993)
    use_ssl     = Column(Boolean, nullable=False, default=True)

    username    = Column(String(255), nullable=True)
    password_encrypted = Column(Text, nullable=True)

    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at  = Column(DateTime, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="mail_accounts", lazy="selectin")

    __table_args__ = (
        Index("ix_mail_accounts_user_email", "user_id", "email"),
    )

    def __repr__(self):
        return f"<MailAccount id={self.id} user_id={self.user_id} email={self.email!r}>"


# =========================
# Report Downloads
# =========================
class ReportDownload(Base):
    __tablename__ = "report_downloads"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    report_type = Column(String(64), nullable=False)  # log_pdf, mail_scan, etc.
    file_path   = Column(String(512), nullable=False)
    ip_address  = Column(String(64), nullable=True)
    user_agent  = Column(String(255), nullable=True)

    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="report_downloads", lazy="selectin")

    __table_args__ = (
        Index("ix_report_downloads_user_created", "user_id", "created_at"),
    )

    def __repr__(self):
        return f"<ReportDownload id={self.id} user_id={self.user_id} type={self.report_type}>"


# =========================
# Allowed IPs
# =========================
class AllowedIP(Base):
    __tablename__ = "allowed_ips"

    id        = Column(Integer, primary_key=True, index=True)
    user_id   = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ip        = Column(String(64), nullable=False)
    label     = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user      = relationship("User", back_populates="allowed_ips", lazy="selectin")

    __table_args__ = (
        Index("ix_allowed_ips_user_ip", "user_id", "ip"),
    )

    def __repr__(self):
        return f"<AllowedIP id={self.id} user_id={self.user_id} ip={self.ip}>"


# =========================
# Payment Events (MP / Stripe / etc)
# =========================
class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(32), nullable=False)   # "mp" | "stripe" | ...
    payment_id = Column(String(128), nullable=False)  # id de pago en el proveedor
    event_type = Column(String(64), nullable=False)   # created | updated | webhook | ...
    status     = Column(String(32), nullable=False, default="pending")

    amount     = Column(Numeric(10, 2), nullable=True)
    currency   = Column(String(8), nullable=True)

    raw_payload = Column(Text, nullable=True)
    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="payment_events", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("provider", "payment_id", name="uq_payment_events_provider_payment"),
        Index("ix_payment_events_user_created", "user_id", "created_at"),
    )

    def __repr__(self):
        return f"<PaymentEvent id={self.id} provider={self.provider} payment_id={self.payment_id} status={self.status}>"


# =========================
# Dark Web Scan Requests
# =========================
class DarkwebScanRequest(Base):
    __tablename__ = "darkweb_scan_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    contact_name = Column(String(255), nullable=True)
    contact_email = Column(String(255), nullable=False)

    targets_emails = Column(Text, nullable=True)   # correos a revisar (uno por línea)
    targets_domains = Column(Text, nullable=True)  # dominios / servicios a revisar
    keywords = Column(Text, nullable=True)         # marca, palabras clave, etc.
    notes = Column(Text, nullable=True)            # contexto adicional

    status = Column(String(32), nullable=False, default="pending")  # pending|in_progress|done|cancelled
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    report_url = Column(String(512), nullable=True)  # opcional: URL del informe generado (PDF/HTML)

    user = relationship("User", back_populates="darkweb_requests", lazy="selectin")

    __table_args__ = (
        Index("ix_darkweb_requests_user_created", "user_id", "created_at"),
    )

    def __repr__(self):
        return f"<DarkwebScanRequest id={self.id} user_id={self.user_id} status={self.status}>"


# =========================
# Payment History (UI/auditoría)
# =========================
class PaymentHistory(Base):
    __tablename__ = "payments_history"

    id                = Column(Integer, primary_key=True, index=True)
    user_id           = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    provider          = Column(String(32), nullable=False)   # mp | stripe
    external_payment_id = Column(String(128), nullable=False)  # id en el proveedor
    plan              = Column(String(32), nullable=False, default="PRO")
    months            = Column(Integer, nullable=False, default=1)
    amount            = Column(Numeric(10, 2), nullable=False)
    currency          = Column(String(8), nullable=False, default="USD")
    status            = Column(String(32), nullable=False, default="approved")
    description       = Column(String(255), nullable=True)
    raw_payload       = Column(Text, nullable=True)
    created_at        = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="payments", lazy="selectin")

    __table_args__ = (
        Index("ix_payments_history_user_created", "user_id", "created_at"),
    )

    def __repr__(self):
        return f"<PaymentHistory id={self.id} user_id={self.user_id} plan={self.plan} status={self.status}>"
