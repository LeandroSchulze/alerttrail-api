from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.database import Base

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default='user')
    # Plan del usuario: FREE | PRO | BUSINESS | ENTERPRISE
    plan = Column(String, default='FREE')
    plan_expires = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class Setting(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(String, nullable=False)

class MailScan(Base):
    __tablename__ = 'mail_scans'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    sender = Column(String)
    subject = Column(String)
    verdict = Column(String)  # SAFE | SUSPICIOUS
    created_at = Column(DateTime, server_default=func.now())

class MailAccount(Base):
    __tablename__ = 'mail_accounts'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    imap_host = Column(String, nullable=False)
    imap_port = Column(Integer, nullable=False, default=993)
    email = Column(String, nullable=False)
    enc_password = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

# --- Opcional: enforcement de IP (si activaste IP_ENFORCEMENT) ---
class AllowedIP(Base):
    __tablename__ = 'allowed_ips'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    ip = Column(String, nullable=False)   # IPv4/IPv6 en texto
    label = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

# --- Soporte simple para Business / Enterprise ---
class Organization(Base):
    __tablename__ = 'organizations'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    owner_user_id = Column(Integer, nullable=False)
    plan = Column(String, default='BUSINESS')  # BUSINESS | ENTERPRISE
    seats_included = Column(Integer, default=25)
    extra_seat_usd = Column(Integer, default=3)
    plan_expires = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class OrgMember(Base):
    __tablename__ = 'org_members'
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, nullable=False)
    user_id = Column(Integer, nullable=False)
    role = Column(String, default='member')  # owner | admin | member
    created_at = Column(DateTime, server_default=func.now())

class ReportDownload(Base):
    __tablename__ = 'report_downloads'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    filename = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
