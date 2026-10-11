"""Application configuration, driven by environment variables / `.env`.

All values are env-overridable using their upper-case field names (e.g.
``OPENAI_API_KEY``, ``LIBSQL_URL``, ``TELEGRAM_BOT_TOKEN``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_home() -> Path:
    return Path("~/.local/share/artemis").expanduser()


class Settings(BaseSettings):
    """Runtime settings for Artemis."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # Accept comma/space-separated lists (e.g. TELEGRAM_ALLOWED_CHAT_IDS)
        # rather than requiring JSON, and tolerate an empty value.
        enable_decoding=False,
    )

    # --- identity -------------------------------------------------------
    owner_id: str = "owner"
    owner_name: str = "Owner"

    # --- model / provider ----------------------------------------------
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    model_name: str = "openai:gpt-4o-mini"
    # Transport resilience: per-request timeout and SDK-level retries.
    model_timeout: float = 60.0
    model_retries: int = 2
    # Optional per-run usage caps (None = unlimited).
    usage_request_limit: int | None = None
    usage_total_tokens_limit: int | None = None
    # Optional Logfire/OpenTelemetry token; when set, pydantic-ai is instrumented.
    logfire_token: str | None = None

    # --- imports --------------------------------------------------------
    max_import_bytes: int = 5_000_000

    # --- storage --------------------------------------------------------
    libsql_url: str | None = None
    libsql_auth_token: str | None = None

    # --- telegram -------------------------------------------------------
    telegram_bot_token: str | None = None
    telegram_allowed_chat_ids: list[int] = Field(default_factory=list)

    # --- local paths ----------------------------------------------------
    # Named `artemis_home` (env ARTEMIS_HOME) so the OS `HOME` env var does not
    # accidentally override the data directory.
    artemis_home: Path = Field(default_factory=_default_home)
    log_level: str = "INFO"

    # --- market data ----------------------------------------------------
    # "manual" (store user-provided prices) or "yfinance" (fetch free quotes).
    price_source: str = "manual"

    # --- external MCP servers ------------------------------------------
    charting_dir: str = "~/Workspaces/agent-mcps/apollo-charting"
    pdf_dir: str = "~/Workspaces/agent-mcps/apollo-pdf-creator"
    charting_mcp_url: str | None = None
    pdf_mcp_url: str | None = None

    # --- A2A ------------------------------------------------------------
    a2a_public_url: str = "http://127.0.0.1:9000"
    a2a_card_name: str = "Artemis"
    a2a_host: str = "127.0.0.1"
    a2a_port: int = 9000
    peers_file: str | None = None

    # --- MCP server -----------------------------------------------------
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8765
    # When the MCP server runs the full agent, bulk/destructive tools still
    # require approval. There is no interactive approver over MCP, so they are
    # denied unless this is explicitly enabled (dangerous; opt-in).
    mcp_auto_approve: bool = False

    @field_validator("telegram_allowed_chat_ids", mode="before")
    @classmethod
    def _split_chat_ids(cls, value: object) -> object:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [int(part) for part in value.replace(",", " ").split() if part]
        return value

    @field_validator("artemis_home", mode="before")
    @classmethod
    def _expand_home(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value).expanduser()
        return value

    # --- derived --------------------------------------------------------
    @property
    def db_path(self) -> Path:
        """Absolute path of the local SQLite/libSQL database file."""
        return self.artemis_home / "artemis.db"

    @property
    def database_url(self) -> str:
        """SQLAlchemy URL for the database (local file unless overridden)."""
        if self.libsql_url:
            return self.libsql_url
        return f"sqlite+libsql:///{self.db_path}"

    @property
    def artifacts_dir(self) -> Path:
        """Directory where generated report artifacts (PNG/PDF) are collected."""
        return self.artemis_home / "artifacts"

    @property
    def charting_path(self) -> Path:
        return Path(self.charting_dir).expanduser()

    @property
    def pdf_path(self) -> Path:
        return Path(self.pdf_dir).expanduser()

    def ensure_dirs(self) -> None:
        self.artemis_home.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def build_model(settings: Settings | None = None):
    """Build the PydanticAI model, pointing at the OpenAI-compatible gateway.

    Dev/test keeps the default OpenAI provider but redirects ``base_url`` at the
    CommandCode gateway when ``OPENAI_BASE_URL`` is set. Transport retries and
    the per-request timeout are handled by the underlying async OpenAI client.
    """
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    settings = settings or get_settings()
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.model_timeout,
        max_retries=settings.model_retries,
    )
    provider = OpenAIProvider(openai_client=client)
    model_name = settings.model_name
    if model_name.startswith("openai:"):
        model_name = model_name.split(":", 1)[1]
    return OpenAIChatModel(model_name, provider=provider)


def model_settings(settings: Settings | None = None):
    """Per-request model settings (timeout)."""
    from pydantic_ai.settings import ModelSettings

    settings = settings or get_settings()
    return ModelSettings(timeout=settings.model_timeout)


def usage_limits(settings: Settings | None = None):
    """Per-run usage caps, or ``None`` when unlimited."""
    from pydantic_ai.usage import UsageLimits

    settings = settings or get_settings()
    if settings.usage_request_limit is None and settings.usage_total_tokens_limit is None:
        return None
    return UsageLimits(
        request_limit=settings.usage_request_limit,
        total_tokens_limit=settings.usage_total_tokens_limit,
    )
