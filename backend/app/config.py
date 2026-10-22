from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "postgresql+asyncpg://vigil:vigil@localhost:5432/vigil"
    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_hours: int = 8
    log_level: str = "INFO"
    registration_mode: str = "open"  # open | closed
    cors_origins: str = "http://localhost:5173"
    public_url: str = "http://localhost:5173"
    metrics_retention_days: int = 30
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    quota_targets: int = 20
    quota_min_interval_s: int = 15
    ingest_min_interval_s: float = 5  # не частіше за один запит /ingest від агента (ТЗ 2.4)


settings = Settings()
