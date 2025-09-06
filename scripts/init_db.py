from app.config import get_settings
settings = get_settings()
print(f"[init_db] DATABASE_URL = {settings.DATABASE_URL}")from app.database import Base, engine, SessionLocal

from app.config import get_settings
from app.models import User
from app.security import get_password_hash

settings = get_settings()

print("[init_db] Creating tables...")
Base.metadata.create_all(bind=engine)

print("[init_db] Bootstrapping admin user...")
db = SessionLocal()
try:
    admin = db.query(User).filter(User.email == settings.ADMIN_EMAIL).first()
    if not admin:
        admin = User(
            name=settings.ADMIN_NAME,
            email=settings.ADMIN_EMAIL,
            hashed_password=get_password_hash(settings.ADMIN_PASS),
            plan="PRO",
        )
        db.add(admin)
        db.commit()
        print("[init_db] Admin created.")
    else:
        print("[init_db] Admin already exists.")
finally:
    db.close()
