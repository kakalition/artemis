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
    assert setup_logfire(Settings(owner_id="owner", logfire_token=None)) is False
