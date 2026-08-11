from ai_friendly_doc.config import ConfluenceConfig
from ai_friendly_doc.confluence_client import ConfluenceClient


def make_config(email: str = "someone", api_token: str = "secret", verify_ssl: bool = True) -> ConfluenceConfig:
    return ConfluenceConfig(
        base_url="https://example.atlassian.net/wiki",
        email=email,
        api_token=api_token,
        verify_ssl=verify_ssl,
    )


def test_basic_auth_sets_session_auth_tuple():
    client = ConfluenceClient(make_config(email="someone@example.com"))
    assert client._session.auth == ("someone@example.com", "secret")


def test_non_email_account_id_works_as_basic_auth_username():
    # 사내 Server/DC 계정 ID는 이메일 형식이 아닐 수 있음 (예: "hong.gildong")
    client = ConfluenceClient(make_config(email="hong.gildong"))
    assert client._session.auth == ("hong.gildong", "secret")


def test_verify_ssl_defaults_to_true():
    client = ConfluenceClient(make_config())
    assert client._session.verify is True


def test_verify_ssl_can_be_disabled_for_self_signed_certs():
    client = ConfluenceClient(make_config(verify_ssl=False))
    assert client._session.verify is False
