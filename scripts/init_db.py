# scripts/init_db.py
import os
import sys

from app.database import Base, engine, SessionLocal
from app.security import get_password_hash
from app.models import User  # asegúrate de que el modelo se llame User

# Env vars esperadas (Render / local)
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

def main():
    ensure_env()
    # Crea tablas si no existen
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == ADMIN_EMAIL).first()

        if user is None:
            # Crear admin nuevo (si no existía)
            user = User(
                name=ADMIN_NAME or "Admin",
                email=ADMIN_EMAIL,
                hashed_password=get_password_hash(ADMIN_PASS),
                plan="PRO",          # <-- Aseguramos PRO
                is_active=True,
            )
            # Si tu modelo tiene 'role'/'is_admin', los fijamos
            set_if_hasattr(user, "role", "admin")
            set_if_hasattr(user, "is_admin", True)

            db.add(user)
            db.commit()
            print(f"[init_db] Admin creado: {ADMIN_EMAIL} (plan=PRO)")
        else:
            # Actualizar datos del admin existente
            changed = False

            if ADMIN_FORCE_RESET:
                user.hashed_password = get_password_hash(ADMIN_PASS)
                changed = True

            if user.plan != "PRO":
                user.plan = "PRO"
                changed = True

            # Fortalecer flags de admin si existen
            if hasattr(user, "role") and getattr(user, "role") != "admin":
                user.role = "admin"
                changed = True
            if hasattr(user, "is_admin") and getattr(user, "is_admin") is not True:
                user.is_admin = True
                changed = True

            if not user.is_active:
                user.is_active = True
                changed = True

            if ADMIN_NAME and user.name != ADMIN_NAME:
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
