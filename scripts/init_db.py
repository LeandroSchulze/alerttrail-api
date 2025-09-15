# scripts/init_db.py
import os
from sqlalchemy import text, inspect
from app.database import engine, SessionLocal
from app.models import Base, User  # Modelos base requeridos

# Si estos modelos existen en tu repo, el import no debe romper el script
try:  # opcional (solo para asegurar metadata completa si existen)
    from app.models import AllowedIP, ReportDownload  # noqa: F401
except Exception:
    pass

from app.security import get_password_hash


# ---------------------------------------------------------------------------
# Creación de tablas (idempotente)
# ---------------------------------------------------------------------------
def ensure_tables():
    """Crea todas las tablas declaradas en app.models si no existen."""
    Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# Migraciones ligeras (sin Alembic): USERS
# ---------------------------------------------------------------------------
def ensure_users_columns():
    """
    Agrega columnas que falten en 'users' cuando la BD ya existía:
      - is_active   BOOLEAN   NOT NULL DEFAULT 1
      - plan        VARCHAR(20) NOT NULL DEFAULT 'free'
      - updated_at  DATETIME (se inicializa con created_at o ahora)
    """
    insp = inspect(engine)
    try:
        cols = {c["name"] for c in insp.get_columns("users")}
    except Exception:
        # Si la tabla no existe aún, la crea create_all y no hay que migrar nada
        return

    with engine.begin() as conn:
        if "is_active" not in cols:
            conn.execute(text(
                "ALTER TABLE users "
                "ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL"
            ))
        if "plan" not in cols:
            conn.execute(text(
                "ALTER TABLE users "
                "ADD COLUMN plan VARCHAR(20) DEFAULT 'free' NOT NULL"
            ))
        if "updated_at" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN updated_at DATETIME"))
            conn.execute(text(
                "UPDATE users SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)"
            ))


# ---------------------------------------------------------------------------
# Migraciones ligeras (sin Alembic): MAIL_ACCOUNTS
# ---------------------------------------------------------------------------
def ensure_mail_accounts_columns():
    """
    Agrega columnas que falten en 'mail_accounts' cuando la BD ya existía:
      - imap_server  VARCHAR(255) NOT NULL DEFAULT 'imap.gmail.com'
      - imap_port    INTEGER      NOT NULL DEFAULT 993
      - use_ssl      BOOLEAN      NOT NULL DEFAULT 1
      - enc_blob     TEXT         NOT NULL DEFAULT ''
      - created_at   DATETIME     (se inicializa con CURRENT_TIMESTAMP)
    """
    insp = inspect(engine)
    # Si la tabla no existe, create_all la creará
    try:
        cols = {c["name"] for c in insp.get_columns("mail_accounts")}
    except Exception:
        Base.metadata.create_all(bind=engine)
        cols = {c["name"] for c in insp.get_columns("mail_accounts")}

    with engine.begin() as conn:
        if "imap_server" not in cols:
            conn.execute(text(
                "ALTER TABLE mail_accounts "
                "ADD COLUMN imap_server VARCHAR(255) DEFAULT 'imap.gmail.com' NOT NULL"
            ))
        if "imap_port" not in cols:
            conn.execute(text(
                "ALTER TABLE mail_accounts "
                "ADD COLUMN imap_port INTEGER DEFAULT 993 NOT NULL"
            ))
        if "use_ssl" not in cols:
            conn.execute(text(
                "ALTER TABLE mail_accounts "
                "ADD COLUMN use_ssl BOOLEAN DEFAULT 1 NOT NULL"
            ))
        if "enc_blob" not in cols:
            conn.execute(text(
                "ALTER TABLE mail_accounts "
                "ADD COLUMN enc_blob TEXT DEFAULT '' NOT NULL"
            ))
        if "created_at" not in cols:
            conn.execute(text("ALTER TABLE mail_accounts ADD COLUMN created_at DATETIME"))

        # Backfill por si quedaron NULL en filas existentes
        conn.execute(text(
            "UPDATE mail_accounts SET imap_server = COALESCE(imap_server, 'imap.gmail.com')"
        ))
        conn.execute(text(
            "UPDATE mail_accounts SET imap_port = COALESCE(imap_port, 993)"
        ))
        conn.execute(text(
            "UPDATE mail_accounts SET use_ssl = COALESCE(use_ssl, 1)"
        ))
        conn.execute(text(
            "UPDATE mail_accounts SET enc_blob = COALESCE(enc_blob, '')"
        ))
        conn.execute(text(
            "UPDATE mail_accounts SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP)"
        ))


# ---------------------------------------------------------------------------
# Seed / actualización de admin
# ---------------------------------------------------------------------------
def seed_admin():
    """
    Crea o actualiza el usuario admin.
    ENV soportadas:
      ADMIN_EMAIL (def: admin@tuempresa.com)
      ADMIN_PASSWORD (def: Admin05112013!)
      ADMIN_NAME (def: Admin)
      ADMIN_PLAN (def: pro)   -> free|pro
      ADMIN_RESET_PASSWORD=1  -> fuerza regenerar el hash
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
            if not u.name:
                u.name = name
            u.plan = plan
            u.is_active = True
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    ensure_tables()
    ensure_users_columns()
    ensure_mail_accounts_columns()
    seed_admin()
    print("[init_db] OK")


if __name__ == "__main__":
    main()
