# scripts/init_db.py
import os
from datetime import datetime
from sqlalchemy import text, inspect, func

from app.database import engine, SessionLocal
from app.models import Base, User  # Modelos base requeridos

# Si estos modelos existen en tu repo, el import no debe romper el script
try:
    from app.models import AllowedIP, ReportDownload  # noqa: F401
except Exception:
    pass

try:
    from app.security import get_password_hash
except Exception:
    from app.utils.security import get_password_hash  # type: ignore


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def masked(s: str) -> str:
    if not s:
        return ""
    if "@" in s:
        name, dom = s.split("@", 1)
        return name[:2] + "***@" + dom
    return s[:2] + "***"

def truthy(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")

def _norm_email(e: str) -> str:
    return (e or "").strip().lower()


# ---------------------------------------------------------------------------
# Creación de tablas (idempotente)
# ---------------------------------------------------------------------------
def ensure_tables():
    # Asegura que los modelos de rules se registren en Base antes del create_all
    try:
        import app.routers.rules  # registra UserRule y UserSetting
    except Exception as e:
        print("[init_db] aviso: no pude registrar modelos de rules:", e)
    Base.metadata.create_all(bind=engine)
    print("[init_db] create_all OK")


# ---------------------------------------------------------------------------
# Migraciones ligeras (sin Alembic): USERS
# ---------------------------------------------------------------------------
def ensure_users_columns():
    insp = inspect(engine)
    try:
        cols = {c["name"] for c in insp.get_columns("users")}
    except Exception:
        print("[init_db] Tabla users no existe aún (será creada por create_all)")
        return

    with engine.begin() as conn:
        if "is_active" not in cols:
            conn.execute(text(
                "ALTER TABLE users "
                "ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL"
            ))
            print("[init_db] users.is_active agregado")

        if "plan" not in cols:
            conn.execute(text(
                "ALTER TABLE users "
                "ADD COLUMN plan VARCHAR(20) DEFAULT 'FREE' NOT NULL"
            ))
            print("[init_db] users.plan agregado")

        if "role" not in cols:
            conn.execute(text(
                "ALTER TABLE users "
                "ADD COLUMN role VARCHAR(20) DEFAULT 'user' NOT NULL"
            ))
            print("[init_db] users.role agregado")

        if "is_admin" not in cols:
            conn.execute(text(
                "ALTER TABLE users "
                "ADD COLUMN is_admin BOOLEAN DEFAULT 0 NOT NULL"
            ))
            print("[init_db] users.is_admin agregado")

        if "is_superuser" not in cols:
            conn.execute(text(
                "ALTER TABLE users "
                "ADD COLUMN is_superuser BOOLEAN DEFAULT 0 NOT NULL"
            ))
            print("[init_db] users.is_superuser agregado")

        if "updated_at" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN updated_at DATETIME"))
            conn.execute(text(
                "UPDATE users SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)"
            ))
            print("[init_db] users.updated_at agregado y backfilled")

        # Normalizaciones útiles
        conn.execute(text("UPDATE users SET plan = UPPER(plan)"))
        conn.execute(text(
            "UPDATE users SET role = COALESCE(role, 'user')"
        ))


# ---------------------------------------------------------------------------
# Migraciones ligeras (sin Alembic): MAIL_ACCOUNTS
# ---------------------------------------------------------------------------
def ensure_mail_accounts_columns():
    insp = inspect(engine)
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
            print("[init_db] mail_accounts.imap_server agregado")
        if "imap_port" not in cols:
            conn.execute(text(
                "ALTER TABLE mail_accounts "
                "ADD COLUMN imap_port INTEGER DEFAULT 993 NOT NULL"
            ))
            print("[init_db] mail_accounts.imap_port agregado")
        if "use_ssl" not in cols:
            conn.execute(text(
                "ALTER TABLE mail_accounts "
                "ADD COLUMN use_ssl BOOLEAN DEFAULT 1 NOT NULL"
            ))
            print("[init_db] mail_accounts.use_ssl agregado")
        if "enc_blob" not in cols:
            conn.execute(text(
                "ALTER TABLE mail_accounts "
                "ADD COLUMN enc_blob TEXT DEFAULT '' NOT NULL"
            ))
            print("[init_db] mail_accounts.enc_blob agregado")
        if "created_at" not in cols:
            conn.execute(text("ALTER TABLE mail_accounts ADD COLUMN created_at DATETIME"))
            print("[init_db] mail_accounts.created_at agregado")

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
        print("[init_db] mail_accounts backfill OK")


# ---------------------------------------------------------------------------
# Seed / actualización de admin
# ---------------------------------------------------------------------------
def seed_admin():
    # Defaults sensatos
    email = _norm_email(os.getenv("ADMIN_EMAIL", "admin@alerttrail.com"))
    password = os.getenv("ADMIN_PASS") or os.getenv("ADMIN_PASSWORD") or "changeme"
    name = os.getenv("ADMIN_NAME", "Admin")
    plan = (os.getenv("ADMIN_PLAN") or "PRO").upper()

    force_reset = truthy(os.getenv("ADMIN_FORCE_RESET")) or truthy(os.getenv("ADMIN_RESET_PASSWORD"))

    db = SessionLocal()
    try:
        u = db.query(User).filter(func.lower(User.email) == email).first()

        def set_password(user, raw):
            if hasattr(user, "password_hash"):
                user.password_hash = get_password_hash(raw)
            elif hasattr(user, "hashed_password"):
                user.hashed_password = get_password_hash(raw)
            else:
                raise RuntimeError("El modelo User no tiene 'password_hash' ni 'hashed_password'.")

        if u:
            changed = False

            # Flags y rol de admin
            role_now = (getattr(u, "role", "") or "").lower()
            if role_now != "admin":
                u.role = "admin"; changed = True
            if not bool(getattr(u, "is_admin", False)):
                u.is_admin = True; changed = True
            if not bool(getattr(u, "is_superuser", False)):
                u.is_superuser = True; changed = True

            # Plan (si difiere)
            if (getattr(u, "plan", "") or "").upper() != plan:
                u.plan = plan; changed = True

            # Nombre (si falta)
            if not getattr(u, "name", None):
                u.name = name; changed = True

            # Activo
            if hasattr(u, "is_active") and not bool(getattr(u, "is_active", True)):
                u.is_active = True; changed = True

            # Password
            has_hash = getattr(u, "password_hash", None) or getattr(u, "hashed_password", None)
            if force_reset or not has_hash:
                set_password(u, password); changed = True

            if changed:
                db.add(u)
                db.commit()
                print(f"[init_db] admin actualizado: {masked(email)} (plan={plan}) "
                      f"{'[password RESET]' if (force_reset or not has_hash) else ''}")
            else:
                print(f"[init_db] admin existe sin cambios: {masked(email)} (plan={plan})")
        else:
            # Crear admin
            u = User(email=email, name=name)
            if hasattr(u, "plan"):
                u.plan = plan
            if hasattr(u, "is_active"):
                u.is_active = True
            # rol y flags
            if hasattr(u, "role"):
                u.role = "admin"
            if hasattr(u, "is_admin"):
                u.is_admin = True
            if hasattr(u, "is_superuser"):
                u.is_superuser = True

            set_password(u, password)
            db.add(u)
            db.commit()
            print(f"[init_db] admin creado: {masked(email)} (plan={plan}) [password SET]")
    except Exception as e:
        db.rollback()
        print(f"[init_db][ERROR] {e}")
        raise
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
