"""Optional observability: Logfire / OpenTelemetry instrumentation.

Enabled only when a token is configured (``LOGFIRE_TOKEN`` or ``LOGFIRE_TOKEN``
via settings) and the optional ``observability`` extra is installed; otherwise
it is a no-op so the core stays dependency-light.
"""

from __future__ import annotations

import os

from artemis.config import Settings, get_settings


def setup_logfire(settings: Settings | None = None) -> bool:
    """Instrument pydantic-ai spans with Logfire. Returns True if enabled."""
    settings = settings or get_settings()
    token = settings.logfire_token or os.environ.get("LOGFIRE_TOKEN")
    if not token:
        return False
    try:
        import logfire
    except ImportError:
        return False
    try:
        logfire.configure(token=token)
        logfire.instrument_pydantic_ai()
    except Exception:  # pragma: no cover - defensive
        return False
    return True
