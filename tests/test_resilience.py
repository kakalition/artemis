import sys
import types

import artemis.observability as observability
from artemis.config import Settings, build_model, model_settings, usage_limits
from artemis.observability import setup_logfire


def test_model_settings_carries_timeout():
    settings = Settings(owner_id="owner", model_timeout=12)
    assert model_settings(settings)["timeout"] == 12


def test_usage_limits_unlimited_by_default():
    assert usage_limits(Settings(owner_id="owner")) is None


def test_usage_limits_values():
    limits = usage_limits(
        Settings(owner_id="owner", usage_request_limit=5, usage_total_tokens_limit=1000)
    )
    assert limits is not None
    assert limits.request_limit == 5
    assert limits.total_tokens_limit == 1000


def test_build_model_constructs_without_network():
    model = build_model(
        Settings(
            owner_id="owner",
            openai_api_key="test-key",
            openai_base_url="http://127.0.0.1:1/v1",
            model_name="openai:gpt-4o-mini",
        )
    )
    assert model is not None


def test_setup_logfire_is_noop_without_token(monkeypatch):
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    assert setup_logfire(Settings(owner_id="owner", observability="off", logfire_token=None)) is False


def _fake_logfire(monkeypatch) -> dict:
    calls: dict = {}
    fake = types.ModuleType("logfire")
    fake.configure = lambda **kwargs: calls.update(kwargs)
    fake.instrument_pydantic_ai = lambda: calls.__setitem__("instrumented", True)
    monkeypatch.setitem(sys.modules, "logfire", fake)
    return calls


def test_console_mode_is_free_and_local(monkeypatch):
    calls = _fake_logfire(monkeypatch)
    settings = Settings(owner_id="owner", observability="console")
    assert setup_logfire(settings) is True
    assert calls["send_to_logfire"] is False
    assert calls["instrumented"] is True


def test_otlp_mode_exports_without_cloud(monkeypatch):
    calls = _fake_logfire(monkeypatch)
    monkeypatch.setattr(observability, "_otlp_processor", lambda s: "PROC")
    settings = Settings(owner_id="owner", observability="otlp")
    assert setup_logfire(settings) is True
    assert calls["send_to_logfire"] is False
    assert calls["additional_span_processors"] == ["PROC"]


def test_unknown_mode_is_noop(monkeypatch):
    _fake_logfire(monkeypatch)
    assert setup_logfire(Settings(owner_id="owner", observability="bogus")) is False
