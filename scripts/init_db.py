import os
from app.database import Base, engine, SessionLocal
from app.models import User
from app.security import get_password_hash

def upsert_admin():
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_pass  = os.getenv("ADMIN_PASS")
    admin_name  = os.getenv("ADMIN_NAME", "Admin")
    force_reset = os.getenv("ADMIN_FORCE_RESET", "0").lower() in ("1", "true", "yes")

    if not admin_email or not admin_pass:
        print(">> ADMIN_EMAIL/ADMIN_PASS no configurados; omitiendo admin seed")
        return

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == admin_email).first()
        if u:
            if force_reset:
                u.name = admin_name
                u.password_hash = get_password_hash(admin_pass)
                u.plan = "pro"
                db.commit()
                print(f">> Admin ACTUALIZADO: {admin_email}")
            else:
                print(f">> Admin ya existe (sin cambios): {admin_email}")
        else:
            u = User(
                email=admin_email,
                name=admin_name,
                password_hash=get_password_hash(admin_pass),
                plan="pro",
            )
            db.add(u)
            db.commit()
            print(f">> Admin CREADO: {admin_email}")
    finally:
        db.close()

def main():
    # Crea tablas si no existen
    Base.metadata.create_all(bind=engine)
    # Crea/actualiza admin
    upsert_admin()

if __name__ == "__main__":
    main()
