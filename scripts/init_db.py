import os, datetime as dt
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_engine
from app.models import User, Setting
from app.security import get_password_hash


engine = get_engine()
# Crear tablas si no existen
Base.metadata.create_all(bind=engine)


# --- Migración automática para columnas nuevas en 'users' ---
with engine.begin() as conn:
cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()} if conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='users'" )).fetchone() else set()
if 'users' not in [r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]:
pass # tabla se creará por Base.metadata.create_all arriba
else:
if 'role' not in cols:
conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR DEFAULT 'user'"))
if 'plan' not in cols:
conn.execute(text("ALTER TABLE users ADD COLUMN plan VARCHAR DEFAULT 'FREE'"))
if 'plan_expires' not in cols:
conn.execute(text("ALTER TABLE users ADD COLUMN plan_expires DATETIME"))
if 'created_at' not in cols:
conn.execute(text("ALTER TABLE users ADD COLUMN created_at DATETIME DEFAULT (CURRENT_TIMESTAMP)"))
# Defaults para filas existentes
conn.execute(text("UPDATE users SET role = COALESCE(role, 'user')"))
conn.execute(text("UPDATE users SET plan = COALESCE(plan, 'FREE')"))


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')
ADMIN_PASS = os.getenv('ADMIN_PASS')
ADMIN_NAME = os.getenv('ADMIN_NAME', 'Admin')
PROMO_ENABLED = os.getenv('PROMO_ENABLED', 'false').lower() == 'true'


with SessionLocal() as db:
# admin
if ADMIN_EMAIL and ADMIN_PASS:
admin = db.query(User).filter(User.email==ADMIN_EMAIL).first()
if not admin:
admin = User(email=ADMIN_EMAIL, name=ADMIN_NAME,
password_hash=get_password_hash(ADMIN_PASS),
role='admin', plan='PRO', plan_expires=None)
db.add(admin)
db.commit()
else:
# asegurar campos
if not getattr(admin, 'role', None): admin.role = 'admin'
if not getattr(admin, 'plan', None): admin.plan = 'PRO'
db.commit()


# settings (promo)
if PROMO_ENABLED:
used = db.query(Setting).filter(Setting.key=='promo_used').first()
if not used:
db.add(Setting(key='promo_used', value='0'))
db.commit()
