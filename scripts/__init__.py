import os
from app.database import Base, engine, SessionLocal
from app.models import User
from app.utils.security import hash_password

def upsert_admin():
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_pass  = os.getenv("ADMIN_PASS")
    admin_name  = os.getenv("ADMIN_NAME", "Admin")
    force_reset = os.getenv("ADMIN_FORCE_RESET", "0") in ("1", "true", "True")

    if not (admin_email and admin_pass):
        print(">> ADMIN_EMAIL/ADMIN_PASS no configurados; omitiendo admin seed")
        return

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == admin_email).first()
        if u:
            if force_reset:
                u.name = admin_name
                u.password_hash = hash_password(admin_pass)
                u.plan = "pro"
                db.commit()
                print(">> Admin ACTUALIZADO:", admin_email)
            else:
                print(">> Admin ya existe (sin cambios):", admin_email)
        else:
            db.add(User(email=admin_email, name=admin_name,
                        password_hash=hash_password(admin_pass), plan="pro"))
            db.commit()
            print(">> Admin CREADO:", admin_email)
    finally:
        db.close()

def main():
    Base.metadata.create_all(bind=engine)
    upsert_admin()

if __name__ == "__main__":
    main()
