"""SOUL.md resolution for Artemis.

The persona is taken from ``./SOUL.md`` (project root) when present, otherwise
from ``$ARTEMIS_HOME/SOUL.md``, otherwise agentkit's default.
"""

from __future__ import annotations

from pathlib import Path

from agentkit.soul import DEFAULT_SOUL, compose_instructions  # noqa: F401  (re-export)
from agentkit.soul import ensure_soul as _ensure_soul
from agentkit.soul import load_soul as _load_soul
from agentkit.soul import soul_path as _soul_path

from artemis.config import Settings, get_settings

PROJECT_SOUL = Path("SOUL.md")


def resolve_soul_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    if PROJECT_SOUL.exists():
        return PROJECT_SOUL
    return _soul_path(settings)


def load_soul(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if PROJECT_SOUL.exists():
        text = PROJECT_SOUL.read_text(encoding="utf-8").strip()
        if text:
            return text
    return _load_soul(settings)


def ensure_soul(settings: Settings | None = None, *, overwrite: bool = False) -> Path:
    """Scaffold a project ``./SOUL.md`` (falling back to the agent home)."""
    if overwrite or not PROJECT_SOUL.exists():
        try:
            PROJECT_SOUL.write_text(DEFAULT_SOUL, encoding="utf-8")
            return PROJECT_SOUL
        except OSError:
            pass
    return _ensure_soul(settings, overwrite=overwrite)


__all__ = [
    "DEFAULT_SOUL",
    "compose_instructions",
    "load_soul",
    "resolve_soul_path",
    "ensure_soul",
]
