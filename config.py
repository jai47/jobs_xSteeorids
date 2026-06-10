from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _REPO_ROOT / ".env"
if not _ENV_FILE.is_file():
    _ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_user: str = "copilot"
    db_password: str = "changeme"
    db_name: str = "career_copilot"
    db_host: str = "db"
    db_port: int = 5432

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    dashboard_secret: str = "changeme"

    log_level: str = "INFO"
    pipeline_cron_hour: int = 2

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()