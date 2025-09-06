from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    APP_NAME: str = "AlertTrail"
    SECRET_KEY: str = "change_this_secret"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Admin bootstrap
    ADMIN_EMAIL: str = "admin@example.com"
    ADMIN_PASS: str = "admin1234"
    ADMIN_NAME: str = "Admin"

    # Plans
    FREE_DAILY_LIMIT: int = 10

    # Database
    DATABASE_URL: str = "sqlite:///./alerttrail.sqlite3"

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
