# scripts/init_db.py
import os
from datetime import datetime
from sqlalchemy import text, inspect, func

from app.database import engine, SessionLocal
from app.models import Base, User  # Modelos base requeridos

# Si estos modelos existen en tu repo, el import no debe romper el script
try:  # opcional (sólo para asegurar metadata completa si existen)
    from app.models import AllowedIP, ReportDownload  # noqa: F401
except Exception:
    pass

# get_password_hash puede estar en app.security o en app.utils.security
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

def truthy(v: str) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")

def _norm_email(e: str) -> str:
    return (e or "").strip().lower()


# ---------------------------------------------------------------------------
# Creación de tablas (idempotente)
# ---------------------------------------------------------------------------
def ensure_tables():
    """Crea todas las tablas declaradas en app.models si no existen."""
    Base.metadata.create_all(bind=engine)
    print("[init_db] create_all OK")


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
                "ADD COLUMN plan VARCHAR(20) DEFAULT 'free' NOT NULL"
            ))
            print("[init_db] users.plan agregado")
        if "updated_at" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN updated_at DATETIME"))
            conn.execute(text(
                "UPDATE users SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)"
            ))
            print("[init_db] users.updated_at agregado y backfilled")


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
        print("[init_db] mail_accounts backfill OK")


# ---------------------------------------------------------------------------
# Seed / actualización de admin (idempotente y robusto)
# ---------------------------------------------------------------------------
def seed_admin():
    """
    Crea o actualiza el usuario admin.

    ENV soportadas (con alias):
      ADMIN_EMAIL (def: admin@tuempresa.com)
      ADMIN_PASS | ADMIN_PASSWORD
      ADMIN_NAME (def: Admin)
      ADMIN_PLAN (def: pro)   -> free|pro
      ADMIN_FORCE_RESET | ADMIN_RESET_PASSWORD -> 1/true/yes/on fuerza reset del hash
    """
    email = _norm_email(os.getenv("ADMIN_EMAIL", "admin@tuempresa.com"))
    # Acepta ambos nombres de variable para compatibilidad
    password = os.getenv("ADMIN_PASS") or os.getenv("ADMIN_PASSWORD") or "Admin05112013!"
    name = os.getenv("ADMIN_NAME", "Admin")
    plan = (os.getenv("ADMIN_PLAN", "pro") or "pro").lower()
    force_reset = truthy(os.getenv("ADMIN_FORCE_RESET")) or truthy(os.getenv("ADMIN_RESET_PASSWORD"))

    db = SessionLocal()
    try:
        # 🔸 Match case-insensitive para evitar problemas de capitalización
        u = db.query(User).filter(func.lower(User.email) == email).first()

        def set_password(user, raw):
            """Setea el hash respetando el nombre del campo del modelo."""
            if hasattr(user, "password_hash"):
                user.password_hash = get_password_hash(raw)
            elif hasattr(user, "hashed_password"):
                user.hashed_password = get_password_hash(raw)
            else:
                raise RuntimeError("El modelo User no tiene 'password_hash' ni 'hashed_password'.")

        if u:
            changed = False
            # Flags y datos básicos
            if hasattr(u, "is_admin") and not getattr(u, "is_admin"):
                u.is_admin = True
                changed = True
            if hasattr(u, "is_active") and not getattr(u, "is_active"):
                u.is_active = True
                changed = True
            if hasattr(u, "plan") and getattr(u, "plan") != plan:
                u.plan = plan
                changed = True
            if not getattr(u, "name", None):
                u.name = name
                changed = True

            # Reset si se solicita o si falta hash
            has_hash = getattr(u, "password_hash", None) or getattr(u, "hashed_password", None)
            if force_reset or not has_hash:
                set_password(u, password)
                changed = True

            if changed:
                db.add(u)
                db.commit()
                print(f"[init_db] admin actualizado: {masked(email)} (plan={plan}) "
                      f"{'[password RESET]' if (force_reset or not has_hash) else ''}")
            else:
                print(f"[init_db] admin existe sin cambios: {masked(email)} (plan={plan})")
        else:
            # Crear usuario admin
            u = User(
                email=email,
                name=name,
            )
            if hasattr(u, "plan"):
                u.plan = plan
            if hasattr(u, "is_active"):
                u.is_active = True
            if hasattr(u, "is_admin"):
                u.is_admin = True

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
