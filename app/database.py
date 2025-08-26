import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

def _sqlite_url():
    # Si hay DATABASE_URL (Postgres, etc), úsala
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    # Preferir /var/data en Render (PORT suele estar seteada)
    use_render_path = bool(os.getenv("RENDER") or os.getenv("PORT"))
    db_path = "/var/data/alerttrail.sqlite3" if use_render_path else "./data/alerttrail.sqlite3"

    # Asegurar que la carpeta exista
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return f"sqlite:///{db_path}"

DATABASE_URL = _sqlite_url()

class Base(DeclarativeBase):
    pass

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)