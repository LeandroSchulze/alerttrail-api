# scripts/init_db.py
import sqlalchemy as sa
from sqlalchemy import text
from app.database import engine, SessionLocal
from app.models import Base, User  # asegura que carga los modelos

def ensure_schema():
    # Crea tablas nuevas si no existen
    Base.metadata.create_all(bind=engine)

    insp = sa.inspect(engine)
    cols = {c["name"] for c in insp.get_columns("users")}

    # Agregar columnas que faltan en SQLite (ALTER TABLE ... ADD COLUMN)
    with engine.begin() as conn:
        if "is_active" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL"))
        if "plan" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN plan VARCHAR(20) DEFAULT 'free' NOT NULL"))
        if "updated_at" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN updated_at DATETIME"))
            # inicializamos con created_at o ahora mismo
            conn.execute(text("UPDATE users SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)"))

    # (opcional) asegurar admin, etc. — deja tu lógica aquí si la tenías
    # with SessionLocal() as db:
    #     ...

if __name__ == "__main__":
    ensure_schema()
    print("[init_db] OK")
