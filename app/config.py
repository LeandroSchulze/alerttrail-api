import os
from pydantic import BaseModel

class Settings(BaseModel):
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "es")
    PYTHON_VERSION: str | None = os.getenv("PYTHON_VERSION")
    DATABASE_URL: str | None = os.getenv("DATABASE_URL")

settings = Settings()
