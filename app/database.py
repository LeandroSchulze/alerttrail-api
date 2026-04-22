import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Leemos la variable de Railway
DATABASE_URL = os.getenv("database_url") or os.getenv("DATABASE_URL") or ""

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./alerttrail.sqlite3"

# CORRECCIÓN CRÍTICA: SQLAlchemy requiere 'postgresql://' (con 'ql')
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Crear engine
if "sqlite" in DATABASE_URL:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # Para Postgres en Railway
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
