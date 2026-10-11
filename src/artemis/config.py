"""Artemis settings — agentkit's :class:`AgentSettings` plus finance options.

Data lives under agentkit's workspace root at ``~/.agentkit/artemis`` by
default; the legacy ``ARTEMIS_HOME`` env var is still honoured as an override.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from agentkit.config import AgentSettings, build_model, model_settings, usage_limits  # noqa: F401
from pydantic import AliasChoices, Field


class Settings(AgentSettings):
    """Artemis runtime settings."""

    agent_name: str = "artemis"

    # Data directory. ``agent_home`` is agentkit's field; accept ARTEMIS_HOME too.
    agent_home: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("ARTEMIS_HOME", "AGENT_HOME"),
    )

    # Storage (legacy env name kept for compatibility).
    libsql_url: str | None = None

    # Domain / integrations
    price_source: str = "manual"
    max_import_bytes: int = 5_000_000
    charting_dir: str = "~/Workspaces/agent-mcps/apollo-charting"
    pdf_dir: str = "~/Workspaces/agent-mcps/apollo-pdf-creator"
    charting_mcp_url: str | None = None
    pdf_mcp_url: str | None = None
    mcp_auto_approve: bool = False

    # --- derived --------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.home / "artemis.db"

    @property
    def resolved_database_url(self) -> str:
        if self.libsql_url:
            return self.libsql_url
        if self.database_url:
            return self.database_url
        return f"sqlite+libsql:///{self.db_path}"

    @property
    def charting_path(self) -> Path:
        return Path(self.charting_dir).expanduser()

    @property
    def pdf_path(self) -> Path:
        return Path(self.pdf_dir).expanduser()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


__all__ = ["Settings", "get_settings", "build_model", "model_settings", "usage_limits"]
