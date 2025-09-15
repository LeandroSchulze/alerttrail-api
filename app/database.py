# app/database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Usa DATABASE_URL si está seteada. Sugerido en Render:
# DATABASE_URL = sqlite:////var/data/alerttrail.sqlite3
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if not DATABASE_URL:
    # Fallbacks: Render (/var/data) o local (./)
    default_render_path = "/var/data/alerttrail.sqlite3"
    if os.path.isdir("/var/data"):
        DATABASE_URL = f"sqlite:///{default_render_path}"
    else:
        DATABASE_URL = "sqlite:///./alerttrail.sqlite3"

# Crear engine (manejo especial para SQLite)
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependency para FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
