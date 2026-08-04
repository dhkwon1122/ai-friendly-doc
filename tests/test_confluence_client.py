import pytest

from ai_friendly_doc.config import ConfluenceConfig
from ai_friendly_doc.confluence_client import ConfluenceClient


def make_config(
    auth_type: str, email: str | None = "someone", api_token: str = "secret", verify_ssl: bool = True
) -> ConfluenceConfig:
    return ConfluenceConfig(
        base_url="https://example.atlassian.net/wiki",
        auth_type=auth_type,
        email=email,
        api_token=api_token,
        verify_ssl=verify_ssl,
    )


def test_basic_auth_sets_session_auth_tuple():
    client = ConfluenceClient(make_config("basic", email="someone@example.com"))
    assert client._session.auth == ("someone@example.com", "secret")


def test_userpass_auth_sets_session_auth_tuple_with_non_email_id():
    # 사내 Server/DC 계정 ID는 이메일 형식이 아닐 수 있음 (예: "hong.gildong")
    client = ConfluenceClient(make_config("userpass", email="hong.gildong"))
    assert client._session.auth == ("hong.gildong", "secret")


def test_bearer_auth_sets_authorization_header():
    client = ConfluenceClient(make_config("bearer", email=None))
    assert client._session.headers["Authorization"] == "Bearer secret"


def test_unsupported_auth_type_raises():
    with pytest.raises(ValueError):
        ConfluenceClient(make_config("digest"))


def test_verify_ssl_defaults_to_true():
    client = ConfluenceClient(make_config("basic"))
    assert client._session.verify is True


def test_verify_ssl_can_be_disabled_for_self_signed_certs():
    client = ConfluenceClient(make_config("basic", verify_ssl=False))
    assert client._session.verify is False
