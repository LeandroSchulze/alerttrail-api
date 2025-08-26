import os
from app.database import Base, engine, SessionLocal
from app.models import User
from app.auth import get_password_hash

def main():
    Base.metadata.create_all(bind=engine)
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_pass = os.getenv("ADMIN_PASS", "changeme123")
    admin_name = os.getenv("ADMIN_NAME", "Admin")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email==admin_email).first()
        if not user:
            user = User(email=admin_email, name=admin_name, hashed_password=get_password_hash(admin_pass))
            db.add(user); db.commit()
            print("Admin creado:", admin_email)
        else:
            print("Admin ya existe:", admin_email)
    finally:
        db.close()

if __name__ == "__main__":
    main()
