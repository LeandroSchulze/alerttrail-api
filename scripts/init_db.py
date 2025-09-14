import os
import datetime as dt
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_engine
from app.models import User, Setting
from app.security import get_password_hash

engine = get_engine()

# 1) Crear tablas base si no existen
Base.metadata.create_all(bind=engine)

# 2) Migración automática de columnas nuevas en 'users'
with engine.begin() as conn:
    # ¿existe la tabla users?
    exists = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    ).fetchone()

    if exists:
        cols_rows = conn.execute(text("PRAGMA table_info(users)")).fetchall()
        cols = {row[1] for row in cols_rows}  # row[1] = nombre de columna

        if 'role' not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR"))
            conn.execute(text("UPDATE users SET role='user' WHERE role IS NULL"))

        if 'plan' not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN plan VARCHAR"))
            conn.execute(text("UPDATE users SET plan='FREE' WHERE plan IS NULL"))

        if 'plan_expires' not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN plan_expires DATETIME"))

        if 'created_at' not in cols:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN created_at DATETIME DEFAULT (CURRENT_TIMESTAMP)")
            )

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')
ADMIN_PASS = os.getenv('ADMIN_PASS')
ADMIN_NAME = os.getenv('ADMIN_NAME', 'Admin')
PROMO_ENABLED = os.getenv('PROMO_ENABLED', 'false').lower() == 'true'

with SessionLocal() as db:
    # 3) Asegurar admin
    if ADMIN_EMAIL and ADMIN_PASS:
        admin = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if not admin:
            admin = User(
                email=ADMIN_EMAIL,
                name=ADMIN_NAME,
                password_hash=get_password_hash(ADMIN_PASS),
                role='admin',
                plan='PRO',
                plan_expires=None,
            )
            db.add(admin)
            db.commit()
        else:
            # Defaults por si venía de un esquema viejo
            if not getattr(admin, 'role', None):
                admin.role = 'admin'
            if not getattr(admin, 'plan', None):
                admin.plan = 'PRO'
            db.commit()

    # 4) Ajustar settings de promo
    if PROMO_ENABLED:
        used = db.query(Setting).filter(Setting.key == 'promo_used').first()
        if not used:
            db.add(Setting(key='promo_used', value='0'))
            db.commit()
