# scripts/init_db.py
import os
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine, Base
from app.models import User  # ajusta el import al path real
from app.security import get_password_hash

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_PASS = os.getenv("ADMIN_PASS")
ADMIN_NAME = os.getenv("ADMIN_NAME", "Admin")
ADMIN_FORCE_RESET = os.getenv("ADMIN_FORCE_RESET", "false").strip().lower() in ("1", "true", "t", "yes", "y")

def upsert_admin(db: Session):
    if not ADMIN_EMAIL or not ADMIN_PASS:
        print("[init_db] ADMIN_EMAIL/ADMIN_PASS faltan; no se crea admin")
        return

    u = db.query(User).filter(User.email == ADMIN_EMAIL).one_or_none()
    hp = get_password_hash(ADMIN_PASS)

    if u is None:
        u = User(
            email=ADMIN_EMAIL,
            name=ADMIN_NAME,
            is_active=True,
            is_admin=True,
            hashed_password=hp,
            password_hash=hp,   # <- normalizamos ambos
        )
        db.add(u)
        db.commit()
        print(f"[init_db] Admin creado: {ADMIN_EMAIL}")
        return

    changed = False
    if ADMIN_FORCE_RESET:
        u.hashed_password = hp
        u.password_hash = hp
        changed = True

    # Aseguramos flags básicos
    if not u.is_active:
        u.is_active = True; changed = True
    if not getattr(u, "is_admin", False):
        u.is_admin = True; changed = True
    if not u.name:
        u.name = ADMIN_NAME; changed = True

    if changed:
        db.add(u)
        db.commit()
        print(f"[init_db] Admin actualizado (reset={ADMIN_FORCE_RESET}): {ADMIN_EMAIL}")
    else:
        print(f"[init_db] Admin ya OK: {ADMIN_EMAIL}")

def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        upsert_admin(db)
    finally:
        db.close()

if __name__ == "__main__":
    main()
