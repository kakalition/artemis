"""Optional observability via Logfire / OpenTelemetry.

Modes (``OBSERVABILITY``):

* ``off``     — no instrumentation (default). A ``LOGFIRE_TOKEN`` alone still
  enables Logfire cloud, for backwards compatibility.
* ``console`` — print spans to the terminal. Free, local, no account.
* ``otlp``    — export spans over OTLP to any backend (Jaeger, Grafana Tempo,
  Arize Phoenix, …) via ``OTLP_ENDPOINT`` / ``OTEL_EXPORTER_OTLP_ENDPOINT``.
  Free and local when the backend runs on your machine.
* ``logfire`` — send to logfire.dev (free tier) using ``LOGFIRE_TOKEN``.

Requires the optional ``observability`` extra; otherwise it is a no-op.
"""

from __future__ import annotations

import os

from artemis.config import Settings, get_settings


def setup_logfire(settings: Settings | None = None) -> bool:
    """Configure observability. Returns True if it was enabled."""
    settings = settings or get_settings()
    mode = settings.observability.strip().lower() or "off"
    token = settings.logfire_token or os.environ.get("LOGFIRE_TOKEN")

    if mode == "off":
        if not token:
            return False
        mode = "logfire"  # token present: implicit cloud enable

    try:
        import logfire
    except ImportError:
        return False

    try:
        if mode == "logfire":
            if not token:
                return False
            logfire.configure(token=token)
        elif mode == "console":
            # console output is on by default once cloud sending is disabled.
            logfire.configure(send_to_logfire=False)
        elif mode == "otlp":
            logfire.configure(
                send_to_logfire=False,
                console=False,
                additional_span_processors=[_otlp_processor(settings)],
            )
        else:
            return False
        logfire.instrument_pydantic_ai()
    except Exception:  # pragma: no cover - defensive
        return False
    return True


def _otlp_processor(settings: Settings):  # pragma: no cover - needs OTEL deps
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint = settings.otlp_endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
    return BatchSpanProcessor(exporter)
