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
plan = Column(String, default='FREE') # FREE | PRO
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
verdict = Column(String) # SAFE | SUSPICIOUS
created_at = Column(DateTime, server_default=func.now())


class MailAccount(Base):
__tablename__ = 'mail_accounts'
id = Column(Integer, primary_key=True)
user_id = Column(Integer, nullable=False)
imap_host = Column(String, nullable=False)
imap_port = Column(Integer, nullable=False, default=993)
email = Column(String, nullable=False)
enc_password = Column(String, nullable=False) # cifrada con Fernet
created_at = Column(DateTime, server_default=func.now())
