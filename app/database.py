import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

def get_engine():
    """
    Devuelve el engine:
    - Postgres si hay DATABASE_URL
    - SQLite persistente en /var/data en Render (con check_same_thread=False)
    """
    url = os.getenv("DATABASE_URL")
    if url and url.strip():
        # Render/Heroku-style URL
        return create_engine(url)
    # SQLite persistente
    os.makedirs("/var/data", exist_ok=True)
    return create_engine(
        "sqlite:////var/data/alerttrail.sqlite3",
        connect_args={"check_same_thread": False},
    )

_engine = get_engine()

SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
