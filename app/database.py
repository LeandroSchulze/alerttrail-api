import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


Base = declarative_base()


def get_engine():
    url = os.getenv('DATABASE_URL')
    if url:
        return create_engine(url)
    # SQLite persistente en Render
    os.makedirs('/var/data', exist_ok=True)
    return create_engine('sqlite:////var/data/alerttrail.sqlite3', connect_args={"check_same_thread": False})


_engine = get_engine()
SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
db.close()
