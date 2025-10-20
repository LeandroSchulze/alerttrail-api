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

    # Organización a la que PERTENECE el usuario
    org_id        = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    is_org_admin  = Column(Boolean, nullable=False, default=False)

    # ================= Verificación por correo =================
    email_verified            = Column(Boolean, nullable=False, default=False)
    verification_code         = Column(String(12), nullable=True)             # p.ej. "123456"
    verification_expires_at   = Column(DateTime, nullable=True)               # vence en ~15 min
    verification_attempts     = Column(Integer, nullable=False, default=0)    # anti-bruteforce

    # ================ Trial PRO (solo particulares) =====================
    # Promo: 5 días sin cargo para cuentas individuales (no empresas/org)
    trial_started_at = Column(DateTime, nullable=True)
    trial_expires_at = Column(DateTime, nullable=True)
    had_trial        = Column(Boolean, nullable=False, default=False)  # evita múltiples trials
    pro_source       = Column(String(32), nullable=True)               # "trial" | "subscription" | None

    # ================ Suscripción PRO (vencimiento + idempotencia) ================
    pro_expires_at  = Column(DateTime, nullable=True)                  # fecha de expiración del PRO
    last_payment_id = Column(String(64), nullable=True)                # para evitar duplicados en webhooks

    # Metadatos
    created_at    = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at    = Column(DateTime, nullable=True)

    # ---------------- Relaciones ----------------
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
    accepted_invites = relationship("OrgInvite", back_populates="used_by_user", lazy="selectin")

    # Pagos
    payment_events = relationship("PaymentEvent", back_populates="user", lazy="selectin")
    payments       = relationship("PaymentHistory", back_populates="user", lazy="selectin")

    # ---------------- Helpers de plan ----------------
    @property
    def is_pro_active(self) -> bool:
        """
        True si el usuario tiene PRO vigente por plan o trial.
        """
        now = datetime.utcnow()
        if self.plan and self.plan.upper() in ("PRO", "BIZ"):
            if self.pro_expires_at:
                return self.pro_expires_at > now
            # Si no hay expiración (legacy), considera PRO activo
            return True
        # Trial aún vigente también habilita funciones PRO
        if self.trial_expires_at and self.trial_expires_at > now:
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
    seats_used     = Column(Integer, nullable=False, default=0)
    billing_id     = Column(String(255), nullable=True)

    created_at     = Column(DateTime, nullable=False, default=datetime.utcnow)

    owner = relationship(
        "User",
        foreign_keys=[owner_user_id],
        back_populates="owned_organizations",
        lazy="selectin",
    )

    members = relationship(
        "User",
        foreign_keys="User.org_id",
        back_populates="organization",
        lazy="selectin",
    )

    invites = relationship(
        "OrgInvite",
        foreign_keys="OrgInvite.org_id",
        back_populates="organization",
        lazy="selectin",
    )

    def __repr__(self):
        return (
            f"<Organization id={self.id} name={self.name!r} "
            f"owner_user_id={self.owner_user_id} seats={self.seats_used}/{self.seats_total}>"
        )


# =========================
# Invitations to Organization
# =========================
class OrgInvite(Base):
    __tablename__ = "org_invites"

    id               = Column(Integer, primary_key=True, index=True)
    org_id           = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    email            = Column(String(255), nullable=True, index=True)
    token            = Column(String(64), nullable=True, unique=True)
    used             = Column(Boolean, nullable=False, default=False)
    used_by_user_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at       = Column(DateTime, nullable=False, default=datetime.utcnow)
    used_at          = Column(DateTime, nullable=True)

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

    imap_host   = Column(String(255), nullable=True)
    imap_server = Column(String(255), nullable=False, default="imap.gmail.com")
    imap_port   = Column(Integer, nullable=False, default=993)
    use_ssl     = Column(Boolean, nullable=False, default=True)

    enc_password = Column(String(1024), nullable=True)
    enc_blob     = Column(Text, nullable=False, default="")

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
    ip_cidr     = Column(String(64), nullable=False)
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


# =========================
# Payment Event (idempotencia webhook)
# =========================
class PaymentEvent(Base):
    """
    Registro crudo por evento de pago del proveedor (p.ej. Mercado Pago).
    Sirve para idempotencia y debugging del webhook.
    """
    __tablename__ = "payment_events"

    id                = Column(Integer, primary_key=True, index=True)
    user_id           = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    provider          = Column(String(32), nullable=False, default="mp")          # "mp" | "stripe" | etc.
    payment_id        = Column(String(128), nullable=False, index=True)           # id del proveedor
    status            = Column(String(32), nullable=True)                         # approved, pending, failed
    plan              = Column(String(20), nullable=True)                         # PRO, BIZ
    amount_cents      = Column(Integer, nullable=True)                            # 1000 = US$10.00
    currency          = Column(String(8), nullable=True, default="USD")
    external_ref      = Column(String(255), nullable=True)                        # lo que enviaste para mapear usuario
    raw_payload       = Column(Text, nullable=True)                               # JSON del evento, como texto
    created_at        = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="payment_events", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("provider", "payment_id", name="uq_payment_events_provider_payment"),
        Index("ix_payment_events_user_created", "user_id", "created_at"),
    )

    def __repr__(self):
        return f"<PaymentEvent id={self.id} provider={self.provider} payment_id={self.payment_id} status={self.status}>"


# =========================
# Payment History (asentado para UI y auditoría)
# =========================
class PaymentHistory(Base):
    """
    Movimientos de pago ya “asentados”: lo que se muestra en /payments_history.
    Cada fila representa una activación/renovación/cargo relevante.
    """
    __tablename__ = "payments_history"

    id                = Column(Integer, primary_key=True, index=True)
    user_id           = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider          = Column(String(32), nullable=False, default="mp")          # "mp", "stripe", etc.
    provider_payment_id = Column(String(128), nullable=True, index=True)
    plan              = Column(String(20), nullable=False, default="PRO")
    period_months     = Column(Integer, nullable=False, default=1)
    amount_cents      = Column(Integer, nullable=True)                            # 1000 = US$10.00
    currency          = Column(String(8), nullable=False, default="USD")
    status            = Column(String(32), nullable=False, default="approved")    # approved, refunded, failed
    description       = Column(String(255), nullable=True)                        # opcional para la UI
    raw_payload       = Column(Text, nullable=True)                               # JSON del cargo (texto)
    created_at        = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="payments", lazy="selectin")

    __table_args__ = (
        Index("ix_payments_history_user_created", "user_id", "created_at"),
    )

    def __repr__(self):
        return f"<PaymentHistory id={self.id} user_id={self.user_id} plan={self.plan} status={self.status}>"
