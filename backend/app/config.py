from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# значення з .env.example та старі типові: з ними токени входу може підробити будь-хто, хто бачив репозиторій
_KNOWN_SECRETS = {"dev-only-change-me", "change-me", "change-me-48-random-chars"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "postgresql+asyncpg://vigil:vigil@localhost:5432/vigil"
    jwt_secret: str  # обов'язковий: типового значення немає
    jwt_ttl_hours: int = 8
    log_level: str = "INFO"
    registration_mode: str = "open"  # open | closed
    cors_origins: str = "http://localhost:5173"
    public_url: str = "http://localhost:5173"
    metrics_retention_days: int = 30
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    quota_targets: int = 20
    ingest_min_interval_s: float = 5  # не частіше за один запит /ingest від агента (ТЗ 2.4)
    max_series_per_target: int = 100  # різних рядів (метрика + instance) від одного об'єкта
    global_users: int = 100  # після цього реєстрація закривається (ТЗ 2.4)
    rate_register_per_min: int = 5  # з однієї IP-адреси (ТЗ розд. 6)
    rate_login_per_min: int = 10
    rate_reset_per_min: int = 5  # запити скидання пароля з однієї IP
    login_lock_after: int = 10  # невдалих входів поспіль на один email
    login_lock_s: int = 900

    @model_validator(mode="after")
    def _strong_secret(self):
        if len(self.jwt_secret) < 32 or self.jwt_secret in _KNOWN_SECRETS:
            raise ValueError(
                "JWT_SECRET має бути випадковим рядком щонайменше з 32 символів, а не значенням із .env.example. "
                'Згенерувати: python -c "import secrets; print(secrets.token_urlsafe(48))"')
        return self


settings = Settings()
