# scripts/init_db.py
import os
from sqlalchemy import text, inspect
from app.database import engine, SessionLocal
from app.models import Base, User  # importa sólo lo seguro

# si tu admin importa otros modelos, no falles si no existen
try:  # opcional: deja preparados si están definidos en app.models
    from app.models import AllowedIP, ReportDownload  # noqa: F401
except Exception:
    pass

# hash de password del admin
from app.security import get_password_hash


def ensure_tables():
    """Crea todas las tablas declaradas en app.models si no existen."""
    Base.metadata.create_all(bind=engine)


def ensure_users_columns():
    """
    Agrega columnas que falten en 'users' cuando la BD ya existía:
    - is_active BOOLEAN NOT NULL DEFAULT 1
    - plan      VARCHAR(20) NOT NULL DEFAULT 'free'
    - updated_at DATETIME (inicializa con created_at o ahora)
    """
    insp = inspect(engine)
    try:
        cols = {c["name"] for c in insp.get_columns("users")}
    except Exception:
        # La tabla todavía no existe; create_all la creará
        return

    with engine.begin() as conn:
        if "is_active" not in cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL"
            ))
        if "plan" not in cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN plan VARCHAR(20) DEFAULT 'free' NOT NULL"
            ))
        if "updated_at" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN updated_at DATETIME"))
            conn.execute(text(
                "UPDATE users SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)"
            ))


def seed_admin():
    """
    Crea/actualiza un admin. Variables de entorno soportadas:
    - ADMIN_EMAIL (def: admin@tuempresa.com)
    - ADMIN_PASSWORD (def: Admin05112013!)
    - ADMIN_NAME (def: Admin)
    - ADMIN_PLAN (def: pro)   -> free|pro
    - ADMIN_RESET_PASSWORD=1  -> fuerza reset del hash
    """
    email = os.getenv("ADMIN_EMAIL", "admin@tuempresa.com").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "Admin05112013!")
    name = os.getenv("ADMIN_NAME", "Admin")
    plan = (os.getenv("ADMIN_PLAN", "pro") or "pro").lower()
    force_reset = os.getenv("ADMIN_RESET_PASSWORD") == "1"

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        if u:
            # actualizar campos clave sin romper lo existente
            if not u.name:
                u.name = name
            u.is_active = True
            u.plan = plan
            if force_reset or not u.password_hash:
                u.password_hash = get_password_hash(password)
            db.add(u)
            db.commit()
            print(f"[init_db] admin actualizado: {email} (plan={plan})")
        else:
            u = User(
                email=email,
                name=name,
                password_hash=get_password_hash(password),
                plan=plan,
                is_active=True,
            )
            db.add(u)
            db.commit()
            print(f"[init_db] admin creado: {email} (plan={plan})")
    finally:
        db.close()


def main():
    ensure_tables()
    ensure_users_columns()
    seed_admin()
    print("[init_db] OK")


if __name__ == "__main__":
    main()
