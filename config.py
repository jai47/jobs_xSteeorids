import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(raw: str) -> str:
    """Turn a Postgres URI into a SQLAlchemy+psycopg2 URL with SSL when needed.

    Accepts `postgres://` and `postgresql://` (Supabase dashboard copies).
    Adds `sslmode=require` for non-local hosts when the query string omits it.
    """
    url = raw.strip()
    if not url:
        return url
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://") :]
    elif url.startswith("postgresql+psycopg2://"):
        pass
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://") :]

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    local = hostname in {"localhost", "127.0.0.1", "db", ""}
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if not local and "sslmode" not in {key.lower() for key in query}:
        query["sslmode"] = "require"
        parsed = parsed._replace(query=urlencode(query))
        url = urlunparse(parsed)
    return url

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _REPO_ROOT / ".env"
if not _ENV_FILE.is_file():
    _ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    db_user: str = "copilot"
    db_password: str = "changeme"
    db_name: str = "career_copilot"
    db_host: str = "db"
    db_port: int = 5432
    # Full URI override (Supabase / Neon / Railway). When set, DB_* parts are ignored.
    database_url_override: str = Field(default="", validation_alias="DATABASE_URL")

    # auto | groq | anthropic | deepseek | google | kimi | azure | aws | opencode | local | openai
    llm_provider: str = "auto"

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"
    google_ai_api_key: str = ""
    google_ai_model: str = "gemini-2.0-flash"
    google_ai_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-02-15-preview"
    aws_region: str = "us-east-1"
    aws_bedrock_model_id: str = ""
    opencode_api_key: str = ""
    opencode_model: str = "mimo-v2.5-free"
    opencode_base_url: str = "https://opencode.ai/zen/v1"
    # Moonshot AI Kimi — OpenAI-compatible endpoint. Confirm the exact model id
    # for your account at platform.moonshot.ai; the default below is a guess.
    kimi_api_key: str = ""
    kimi_model: str = "kimi-k2-0905-preview"
    kimi_base_url: str = "https://api.moonshot.ai/v1"
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
    cors_origins: str = (
        "http://localhost:3000,http://localhost:5173,"
        "https://ai-career-copilot-gold-gamma.vercel.app,"
        "https://jobs.spanwrap.com"
    )

    email_provider: str = "console"
    resend_api_key: str = ""
    email_from_address: str = "copilot@localhost"
    app_base_url: str = "http://localhost:5173"
    api_base_url: str = "http://localhost:8000"
    notification_drain_interval_min: int = 15

    # Adzuna India job board (https://developer.adzuna.com/signup). Empty = skip source.
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        """Origins allowed by CORS. Trailing slashes and quotes are stripped.

        APP_BASE_URL is always included so a Vercel URL set there works even if
        CORS_ORIGINS was left as localhost.
        """
        seen: set[str] = set()
        origins: list[str] = []
        candidates = [part for part in self.cors_origins.split(",")]
        candidates.append(self.app_base_url)
        for raw in candidates:
            origin = raw.strip().strip("\"'").rstrip("/")
            if not origin or origin in seen or not origin.startswith("http"):
                continue
            seen.add(origin)
            origins.append(origin)
        return origins

    @property
    def cors_origin_regex(self) -> str:
        """Allow Vercel URLs and any https host already listed in CORS_ORIGINS / APP_BASE_URL."""
        hosts = [
            r"([a-z0-9-]+\.)*vercel\.app",
            r"([a-z0-9-]+\.)*spanwrap\.com",
        ]
        for origin in self.cors_origins_list:
            hostname = urlparse(origin).hostname or ""
            if hostname and "vercel.app" not in hostname:
                hosts.append(re.escape(hostname))
        return r"https://(" + "|".join(hosts) + r")"

    @property
    def database_url(self) -> str:
        override = (self.database_url_override or "").strip()
        if override:
            return normalize_database_url(override)
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def uses_pgbouncer(self) -> bool:
        """True when DATABASE_URL points at a transaction pooler (Supabase :6543)."""
        url = self.database_url.lower()
        parsed = urlparse(url)
        port = parsed.port
        host = parsed.hostname or ""
        return port == 6543 or "pooler.supabase.com" in host

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    def assert_safe_for_production(self) -> None:
        """Refuse to boot in production with insecure default secrets."""
        if not self.is_production:
            return
        checks: list[tuple[str, str]] = [("DASHBOARD_SECRET", self.dashboard_secret)]
        if not (self.database_url_override or "").strip():
            checks.append(("DB_PASSWORD", self.db_password))
        insecure = [name for name, value in checks if value == "changeme"]
        if insecure:
            raise RuntimeError(
                "Refusing to start with APP_ENV=production while insecure default value(s) "
                f"are still set: {', '.join(insecure)}. Set real secrets in the environment/.env file."
            )


settings = Settings()