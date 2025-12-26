# scripts/init_db.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.database import Base, engine, SessionLocal
from app.models import User
from app.security import get_password_hash


def main():
    Base.metadata.create_all(bind=engine)
    print("[init_db] create_all OK")

    db = SessionLocal()
    try:
        # Crear admin si no existe
        admin_email = "admin@alerttrail.com"
        u = db.query(User).filter(User.email == admin_email).first()
        if not u:
            u = User(
                email=admin_email,
                hashed_password=get_password_hash("admin123"),
            )
            # defaults
            if hasattr(u, "role"):
                u.role = "admin"
            if hasattr(u, "name"):
                u.name = "Admin"
            db.add(u)
            db.commit()
            db.refresh(u)

        # Asegurar admin PRO (para que no quede FREE)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if hasattr(u, "plan"):
            u.plan = "PRO"
        if hasattr(u, "is_pro"):
            u.is_pro = True
        if hasattr(u, "pro_expires_at"):
            u.pro_expires_at = now + timedelta(days=365)

        db.commit()
        print(f"[init_db] Admin actualizado id={u.id}, email={u.email}")
        print("[init_db] done")

    finally:
        db.close()


if __name__ == "__main__":
    main()
