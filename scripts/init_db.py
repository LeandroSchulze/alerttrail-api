from app.database import Base, engine, SessionLocal
from app.config import get_settings
from app.models import User
from app.security import get_password_hash

def bootstrap():
    settings = get_settings()
    admin_email = (settings.ADMIN_EMAIL or "").strip().lower()
    admin_name  = (settings.ADMIN_NAME  or "Admin").strip()
    admin_pass  = (settings.ADMIN_PASS  or "Cambiar123!").strip()

    print(f"[init_db] DATABASE_URL = {settings.DATABASE_URL}")
    print(f"[init_db] ADMIN_EMAIL = {admin_email}")
    print("[init_db] Creating tables...")
    Base.metadata.create_all(bind=engine)

    print("[init_db] Bootstrapping admin from ENV...")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == admin_email).first()
        if not admin:
            print("[init_db] Creating admin...")
            admin = User(
                name=admin_name,
                email=admin_email,
                hashed_password=get_password_hash(admin_pass),
                plan="PRO",
            )
            db.add(admin); db.commit()
            print("[init_db] Admin created.")
        else:
            print("[init_db] Updating admin...")
            admin.name = admin_name
            admin.plan = "PRO"
            admin.hashed_password = get_password_hash(admin_pass)
            db.commit()
            print("[init_db] Admin updated.")
    finally:
        db.close()

if __name__ == "__main__":
    bootstrap()