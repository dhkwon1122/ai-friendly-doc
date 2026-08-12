import pytest
import requests

from ai_friendly_doc.config import DEFAULT_WEB_BASE_URL, ConfluenceConfig
from ai_friendly_doc.confluence_client import DEFAULT_USER_AGENT, ConfluenceClient


def make_config(api_token: str = "secret", verify_ssl: bool = True, web_base_url: str | None = None) -> ConfluenceConfig:
    kwargs = {}
    if web_base_url is not None:
        kwargs["web_base_url"] = web_base_url
    return ConfluenceConfig(
        base_url="https://example.atlassian.net/wiki",
        api_token=api_token,
        verify_ssl=verify_ssl,
        **kwargs,
    )


def test_bearer_auth_sets_authorization_header():
    # 다수의 사내 Confluence Server/DC가 관리자 설정으로 Basic Auth 자체를
    # 꺼두므로("Basic Authentication has been disabled on this instance"),
    # 계정 ID/비밀번호가 아니라 PAT(Bearer) 인증만 쓴다.
    client = ConfluenceClient(make_config(api_token="my-pat-token"))
    assert client._session.headers["Authorization"] == "Bearer my-pat-token"
    assert client._session.auth is None


def test_bearer_auth_strips_whitespace_from_token():
    # PAT을 복사-붙여넣기하는 과정에서 앞뒤 공백/개행이 섞여 들어가기 쉽다 -
    # 자격증명 자체는 맞아도 Authorization 헤더 값이 미묘하게 달라져 401이
    # 나는 흔한 원인이라 방어적으로 strip해야 한다.
    client = ConfluenceClient(make_config(api_token="  my-pat-token\n"))
    assert client._session.headers["Authorization"] == "Bearer my-pat-token"


def test_accept_header_requests_json():
    # 일부 사내 게이트웨이는 Accept 헤더가 없으면 REST API 대신 브라우저용
    # 로그인/HTML 흐름으로 요청을 취급해 인증 결과가 달라진다.
    client = ConfluenceClient(make_config())
    assert client._session.headers["Accept"] == "application/json"


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
    # WAF/게이트웨이나 Confluence 자체(예: "Basic Authentication has been
    # disabled on this instance")가 막은 경우 응답 본문에 진짜 차단 사유가
    # 담겨 있는 경우가 많다 - raise_for_status()만 쓰면 이 정보가 사라지므로,
    # 에러 메시지에 그대로 포함되는지 확인한다.
    fake_response = _FakeResponse(status_code=403, text="Blocked by WAF: unauthorized user agent")
    client = ConfluenceClient(make_config(), session=_FakeSession(fake_response))

    with pytest.raises(requests.HTTPError, match="Blocked by WAF: unauthorized user agent"):
        client.get_page("123")


def test_get_page_error_without_body_falls_back_to_plain_message():
    fake_response = _FakeResponse(status_code=403, text="")
    client = ConfluenceClient(make_config(), session=_FakeSession(fake_response))

    with pytest.raises(requests.HTTPError, match="403 Client Error"):
        client.get_page("123")


def test_get_page_error_includes_base_url_and_token_length_for_diagnosis():
    # "인증 방식 문제가 아닌데도 403"이 재현될 때, 실제로 어떤 base_url로
    # 요청했는지와 토큰이 비어있지 않은지가 에러에 그대로 보여야 - 예전
    # 방식으로 저장해둔 값을 재저장하지 않고 그대로 쓰고 있어서 토큰이 비어
    # 있거나 기대와 다른 경우를 사용자가 바로 알아챌 수 있다.
    fake_response = _FakeResponse(status_code=403, text="")
    client = ConfluenceClient(make_config(api_token="abcdefgh"), session=_FakeSession(fake_response))

    with pytest.raises(requests.HTTPError, match=r"PAT 길이: 8"):
        client.get_page("123")


def test_iter_space_pages_error_includes_response_body_for_diagnosis():
    fake_response = _FakeResponse(status_code=403, text="Blocked by WAF: IP not allowed")
    client = ConfluenceClient(make_config(), session=_FakeSession(fake_response))

    with pytest.raises(requests.HTTPError, match="Blocked by WAF: IP not allowed"):
        list(client.iter_space_pages("ENG"))


def _make_page_json(links_base: str = "https://api-gateway.internal.example.com", attachment_results: list | None = None) -> dict:
    return {
        "id": "123",
        "title": "테스트 문서",
        "space": {"key": "ENG"},
        "version": {"number": 1},
        "body": {"storage": {"value": "<p>본문</p>"}},
        "_links": {"webui": "/spaces/ENG/pages/123", "base": links_base},
        "children": {"attachment": {"results": attachment_results or []}},
    }


def test_get_page_web_url_uses_configured_web_base_url_not_api_links_base():
    # API 응답의 _links.base는 API 게이트웨이 주소를 가리키는 경우가 흔해서
    # (REST 호출용 base_url과 겹치거나 사람이 못 쓰는 내부 주소), 원본 문서
    # 링크에는 그 값 대신 설정된 web_base_url을 항상 써야 한다.
    fake_response = _FakeResponse(status_code=200, json_data=_make_page_json())
    client = ConfluenceClient(make_config(web_base_url="https://confluence.samsungds.net"), session=_FakeSession(fake_response))

    page = client.get_page("123")

    assert page.web_url == "https://confluence.samsungds.net/spaces/ENG/pages/123"


def test_get_page_web_url_defaults_to_org_default_when_unset():
    fake_response = _FakeResponse(status_code=200, json_data=_make_page_json())
    client = ConfluenceClient(make_config(), session=_FakeSession(fake_response))

    page = client.get_page("123")

    assert page.web_url == f"{DEFAULT_WEB_BASE_URL}/spaces/ENG/pages/123"


def test_get_page_expand_param_includes_children_attachment():
    # 첨부파일(이미지 등) 다운로드 링크를 만들려면 body.storage/version/space
    # 뿐 아니라 children.attachment도 같이 받아와야 한다.
    fake_response = _FakeResponse(status_code=200, json_data=_make_page_json())
    fake_session = _FakeSession(fake_response)
    client = ConfluenceClient(make_config(), session=fake_session)
    captured = {}
    original_get = fake_session.get

    def capturing_get(url, params=None):
        captured["params"] = params
        return original_get(url, params=params)

    fake_session.get = capturing_get
    client.get_page("123")

    assert "children.attachment" in captured["params"]["expand"]


def test_get_page_parses_attachments_with_real_download_url():
    # API 응답의 children.attachment.results에서 파일명과 다운로드 경로를
    # 뽑아서, 원본 문서 링크와 마찬가지로 web_base_url을 기준으로 절대
    # 주소를 만들어야 한다(URL 패턴을 추측하지 않고 API가 알려준 실제 경로 사용).
    attachment_results = [
        {"title": "diagram.png", "_links": {"download": "/download/attachments/123/diagram.png"}},
        {"title": "notes.txt", "_links": {"download": "/download/attachments/123/notes.txt"}},
    ]
    fake_response = _FakeResponse(status_code=200, json_data=_make_page_json(attachment_results=attachment_results))
    client = ConfluenceClient(
        make_config(web_base_url="https://confluence.samsungds.net"), session=_FakeSession(fake_response)
    )

    page = client.get_page("123")

    assert len(page.attachments) == 2
    assert page.attachments[0].filename == "diagram.png"
    assert page.attachments[0].download_url == "https://confluence.samsungds.net/download/attachments/123/diagram.png"
    assert page.attachments[1].filename == "notes.txt"


def test_get_page_skips_attachments_without_filename_or_download_link():
    attachment_results = [
        {"title": "broken.png"},  # download 링크 없음
        {"_links": {"download": "/download/attachments/123/x.png"}},  # 파일명 없음
    ]
    fake_response = _FakeResponse(status_code=200, json_data=_make_page_json(attachment_results=attachment_results))
    client = ConfluenceClient(make_config(), session=_FakeSession(fake_response))

    page = client.get_page("123")

    assert page.attachments == []


def test_get_page_attachments_default_empty_when_no_children_field():
    raw = _make_page_json()
    del raw["children"]
    fake_response = _FakeResponse(status_code=200, json_data=raw)
    client = ConfluenceClient(make_config(), session=_FakeSession(fake_response))

    page = client.get_page("123")

    assert page.attachments == []
