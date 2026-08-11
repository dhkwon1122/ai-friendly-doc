import pytest

from ai_friendly_doc.config import ConfigError, load_confluence_config, parse_bool_env


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "off"])
def test_parse_bool_env_falsy_values(value):
    assert parse_bool_env(value, default=True) is False


@pytest.mark.parametrize("value", ["true", "True", "1", "yes", "anything-else"])
def test_parse_bool_env_truthy_values(value):
    assert parse_bool_env(value, default=False) is True


def test_parse_bool_env_uses_default_when_unset():
    assert parse_bool_env(None, default=True) is True
    assert parse_bool_env(None, default=False) is False
    assert parse_bool_env("   ", default=True) is True


def _base_env(monkeypatch, **overrides):
    monkeypatch.delenv("CONFLUENCE_VERIFY_SSL", raising=False)
    env = {
        "CONFLUENCE_BASE_URL": "https://example.atlassian.net/wiki",
        "CONFLUENCE_API_TOKEN": "token",
    }
    env.update(overrides)
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


def test_load_confluence_config_verify_ssl_defaults_true(monkeypatch):
    _base_env(monkeypatch)
    config = load_confluence_config()
    assert config.verify_ssl is True


def test_load_confluence_config_verify_ssl_can_be_disabled(monkeypatch):
    _base_env(monkeypatch, CONFLUENCE_VERIFY_SSL="false")
    config = load_confluence_config()
    assert config.verify_ssl is False


def test_load_confluence_config_requires_api_token(monkeypatch):
    _base_env(monkeypatch, CONFLUENCE_API_TOKEN=None)
    with pytest.raises(ConfigError, match="CONFLUENCE_API_TOKEN"):
        load_confluence_config()
