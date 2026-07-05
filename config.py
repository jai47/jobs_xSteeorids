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
    opencode_api_key: str = ""
    opencode_model: str = "mimo-v2.5-free"
    opencode_base_url: str = "https://opencode.ai/zen/v1"
    local_llm_base_url: str = ""
    local_llm_model: str = "llama3.2"
    local_llm_api_key: str = "ollama"
    # auto = try LLM providers then heuristic; llm = LLM only; heuristic = free local parsing
    resume_parser_mode: str = "auto"
    dashboard_secret: str = "changeme"

    # development | production — gates default-secret enforcement and error detail exposure.
    app_env: str = "development"

    log_level: str = "INFO"
    pipeline_cron_hour: int = 2
    resume_storage_path: str = str(_REPO_ROOT / "resumes")
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    email_provider: str = "console"
    resend_api_key: str = ""
    email_from_address: str = "copilot@localhost"
    app_base_url: str = "http://localhost:5173"
    api_base_url: str = "http://localhost:8000"
    notification_drain_interval_min: int = 15

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    def assert_safe_for_production(self) -> None:
        """Refuse to boot in production with insecure default secrets."""
        if not self.is_production:
            return
        insecure = [
            name
            for name, value in (("DASHBOARD_SECRET", self.dashboard_secret), ("DB_PASSWORD", self.db_password))
            if value == "changeme"
        ]
        if insecure:
            raise RuntimeError(
                "Refusing to start with APP_ENV=production while insecure default value(s) "
                f"are still set: {', '.join(insecure)}. Set real secrets in the environment/.env file."
            )


settings = Settings()