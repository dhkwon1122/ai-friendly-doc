import pytest
import requests

from ai_friendly_doc.config import ConfluenceConfig
from ai_friendly_doc.confluence_client import DEFAULT_USER_AGENT, ConfluenceClient


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


def test_default_user_agent_is_browser_like(monkeypatch):
    monkeypatch.delenv("CONFLUENCE_USER_AGENT", raising=False)
    client = ConfluenceClient(make_config())
    assert client._session.headers["User-Agent"] == DEFAULT_USER_AGENT
    assert "Mozilla" in DEFAULT_USER_AGENT  # 기본 python-requests UA 대신 브라우저처럼 보이는 값이어야 함


def test_user_agent_overridable_via_env(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_USER_AGENT", "my-custom-agent/1.0")
    client = ConfluenceClient(make_config())
    assert client._session.headers["User-Agent"] == "my-custom-agent/1.0"


class _FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data if json_data is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} Client Error: Forbidden for url: https://example.atlassian.net/wiki/x",
                response=self,
            )

    def json(self):
        return self._json_data


class _FakeSession:
    def __init__(self, response):
        self.headers = {}
        self.auth = None
        self.verify = None
        self._response = response

    def get(self, url, params=None):
        return self._response


def test_get_page_error_includes_response_body_for_diagnosis():
    # WAF/게이트웨이가 막은 경우 응답 본문에 진짜 차단 사유가 담겨 있는 경우가
    # 많다 - raise_for_status()만 쓰면 이 정보가 사라지므로, 에러 메시지에
    # 그대로 포함되는지 확인한다.
    fake_response = _FakeResponse(status_code=403, text="Blocked by WAF: unauthorized user agent")
    client = ConfluenceClient(make_config(), session=_FakeSession(fake_response))

    with pytest.raises(requests.HTTPError, match="Blocked by WAF: unauthorized user agent"):
        client.get_page("123")


def test_get_page_error_without_body_falls_back_to_plain_message():
    fake_response = _FakeResponse(status_code=403, text="")
    client = ConfluenceClient(make_config(), session=_FakeSession(fake_response))

    with pytest.raises(requests.HTTPError, match="403 Client Error"):
        client.get_page("123")


def test_iter_space_pages_error_includes_response_body_for_diagnosis():
    fake_response = _FakeResponse(status_code=403, text="Blocked by WAF: IP not allowed")
    client = ConfluenceClient(make_config(), session=_FakeSession(fake_response))

    with pytest.raises(requests.HTTPError, match="Blocked by WAF: IP not allowed"):
        list(client.iter_space_pages("ENG"))
