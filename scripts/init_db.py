# scripts/init_db.py
import os
import sys
from sqlalchemy import text

from app.database import Base, engine, SessionLocal
from app.security import get_password_hash
from app.models import User

# Env vars esperadas
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip()
ADMIN_PASS = os.getenv("ADMIN_PASS", "").strip()
ADMIN_NAME = os.getenv("ADMIN_NAME", "Admin").strip()
ADMIN_FORCE_RESET = os.getenv("ADMIN_FORCE_RESET", "false").lower() in {"1", "true", "yes"}

def ensure_env():
    missing = []
    if not ADMIN_EMAIL:
        missing.append("ADMIN_EMAIL")
    if not ADMIN_PASS:
        missing.append("ADMIN_PASS")
    if missing:
        print(f"[init_db] Faltan variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

def set_if_hasattr(obj, field: str, value):
    if hasattr(obj, field):
        try:
            setattr(obj, field, value)
        except Exception:
            pass

def ensure_user_is_active_column():
    """
    Asegura que exista la columna users.is_active.
    Para SQLite usamos PRAGMA; si falta, la creamos con ALTER TABLE.
    Para Postgres/otros consultamos information_schema.
    """
    with engine.connect() as conn:
        dialect = conn.dialect.name
        has_column = False

        if dialect == "sqlite":
            result = conn.execute(text("PRAGMA table_info(users);"))
            cols = [row[1] for row in result]  # nombre de columna en idx 1
            has_column = "is_active" in cols
            if not has_column:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1;"))
        else:
            q = text("""
                SELECT 1
                FROM information_schema.columns
                WHERE table_name='users' AND column_name='is_active'
                LIMIT 1;
            """)
            has_column = conn.execute(q).scalar() is not None
            if not has_column:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE;"))

        if not has_column:
            print("[init_db] Columna users.is_active creada")
        else:
            print("[init_db] Columna users.is_active OK")

def main():
    ensure_env()

    # Crea tablas si no existen
    Base.metadata.create_all(bind=engine)

    # Asegura la columna nueva (si la tabla ya existía)
    ensure_user_is_active_column()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == ADMIN_EMAIL).first()

        if user is None:
            # Crear admin nuevo
            user = User(
                name=ADMIN_NAME or "Admin",
                email=ADMIN_EMAIL,
                hashed_password=get_password_hash(ADMIN_PASS),
                plan="PRO",
                is_active=True,
            )
            # Si tu modelo tiene 'role' o 'is_admin', los fijamos sin romper
            set_if_hasattr(user, "role", "admin")
            set_if_hasattr(user, "is_admin", True)

            db.add(user)
            db.commit()
            print(f"[init_db] Admin creado: {ADMIN_EMAIL} (plan=PRO)")
        else:
            changed = False

            if ADMIN_FORCE_RESET:
                user.hashed_password = get_password_hash(ADMIN_PASS)
                changed = True

            if getattr(user, "plan", "FREE") != "PRO":
                user.plan = "PRO"
                changed = True

            # Asegurar activo
            if hasattr(user, "is_active") and getattr(user, "is_active") is not True:
                user.is_active = True
                changed = True

            # Fortalecer flags de admin si existen
            if hasattr(user, "role") and getattr(user, "role") != "admin":
                user.role = "admin"
                changed = True
            if hasattr(user, "is_admin") and getattr(user, "is_admin") is not True:
                user.is_admin = True
                changed = True

            if ADMIN_NAME and getattr(user, "name", "") != ADMIN_NAME:
                user.name = ADMIN_NAME
                changed = True

            if changed:
                db.add(user)
                db.commit()
                print(f"[init_db] Admin actualizado: {ADMIN_EMAIL} (plan=PRO)")
            else:
                print(f"[init_db] Admin ya estaba OK: {ADMIN_EMAIL} (plan=PRO)")

    finally:
        db.close()

if __name__ == "__main__":
    main()
