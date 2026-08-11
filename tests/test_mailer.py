import json

import pytest
import requests

from ai_friendly_doc.web.mailer import MailConfigError, is_mail_configured, send_report_email


def _set_full_config(monkeypatch, **overrides):
    values = {
        "MAIL_API_TOKEN": "test-token",
        "MAIL_API_SYSTEM_ID": "sys-123",
        "MAIL_API_USER_ID": "user-456",
    }
    values.update(overrides)
    for key, value in values.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


def test_is_mail_configured_false_when_token_unset(monkeypatch):
    monkeypatch.delenv("MAIL_API_TOKEN", raising=False)
    assert is_mail_configured() is False


def test_is_mail_configured_true_when_token_set(monkeypatch):
    monkeypatch.setenv("MAIL_API_TOKEN", "test-token")
    assert is_mail_configured() is True


@pytest.mark.parametrize("missing", ["MAIL_API_TOKEN", "MAIL_API_SYSTEM_ID", "MAIL_API_USER_ID"])
def test_send_report_email_raises_when_required_env_missing(monkeypatch, missing):
    _set_full_config(monkeypatch, **{missing: None})
    with pytest.raises(MailConfigError, match=missing):
        send_report_email("someone@example.com", subject="제목", body_html="<p>본문</p>")


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {"mailId": "mail-1"}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

    def json(self):
        return self._json_body


def test_send_report_email_posts_multipart_mail_part(monkeypatch):
    _set_full_config(monkeypatch, MAIL_API_SENDER_ADDRESS="bot@example.com")

    captured = {}

    def _fake_post(url, params=None, headers=None, files=None, timeout=None, proxies=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["files"] = files
        captured["timeout"] = timeout
        captured["proxies"] = proxies
        return _FakeResponse()

    monkeypatch.setattr("ai_friendly_doc.web.mailer.requests.post", _fake_post)

    send_report_email("someone@example.com", subject="분석 리포트", body_html="<p>본문 내용</p>")

    assert captured["url"] == "https://openapi.samsung.net/mail/api/v2.0/mails/send"
    assert captured["params"] == {"userID": "user-456"}
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["headers"]["System-ID"] == "sys-123"
    assert captured["proxies"] is None  # MAIL_API_NO_PROXY 미설정 시 기본 동작(환경변수 프록시를 따름) 유지

    filename, content, content_type = captured["files"]["mail"]
    assert filename is None
    assert content_type == "application/json;charset=utf-8"
    payload = json.loads(content.decode("utf-8"))
    assert payload["subject"] == "분석 리포트"
    assert payload["contents"] == "<p>본문 내용</p>"
    assert payload["contentType"] == "html"
    assert payload["docSecuType"] == "PERSONAL"
    assert payload["sender"] == {"emailAddress": "bot@example.com"}
    assert payload["recipients"] == [{"emailAddress": "someone@example.com", "recipientType": "TO"}]


def test_send_report_email_defaults_sender_to_user_id(monkeypatch):
    _set_full_config(monkeypatch, MAIL_API_SENDER_ADDRESS=None)

    def _fake_post(url, params=None, headers=None, files=None, timeout=None, proxies=None):
        return _FakeResponse()

    captured_payload = {}

    def _capturing_post(url, params=None, headers=None, files=None, timeout=None, proxies=None):
        captured_payload["payload"] = json.loads(files["mail"][1].decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setattr("ai_friendly_doc.web.mailer.requests.post", _capturing_post)

    send_report_email("someone@example.com", subject="제목", body_html="<p>본문</p>")

    assert captured_payload["payload"]["sender"] == {"emailAddress": "user-456"}


def test_send_report_email_uses_custom_base_url(monkeypatch):
    _set_full_config(monkeypatch, MAIL_API_BASE_URL="https://mail.internal.example.com/api/v9/")

    captured = {}

    def _fake_post(url, **kwargs):
        captured["url"] = url
        return _FakeResponse()

    monkeypatch.setattr("ai_friendly_doc.web.mailer.requests.post", _fake_post)

    send_report_email("someone@example.com", subject="제목", body_html="<p>본문</p>")

    assert captured["url"] == "https://mail.internal.example.com/api/v9/mails/send"


def test_send_report_email_raises_on_http_error_status(monkeypatch):
    _set_full_config(monkeypatch)
    monkeypatch.setattr(
        "ai_friendly_doc.web.mailer.requests.post", lambda *a, **k: _FakeResponse(status_code=401)
    )

    with pytest.raises(MailConfigError, match="401"):
        send_report_email("someone@example.com", subject="제목", body_html="<p>본문</p>")


def test_send_report_email_http_error_includes_response_body(monkeypatch):
    # 401/403만으로는 실제 원인(토큰 만료, System-ID/userID 불일치 등)을 알 수
    # 없는 경우가 많다 - Confluence 클라이언트와 마찬가지로 응답 본문이 있으면
    # 에러 메시지에 그대로 포함되는지 확인한다.
    _set_full_config(monkeypatch)
    monkeypatch.setattr(
        "ai_friendly_doc.web.mailer.requests.post",
        lambda *a, **k: _FakeResponse(status_code=401, text='{"message":"invalid or expired token"}'),
    )

    with pytest.raises(MailConfigError, match="invalid or expired token"):
        send_report_email("someone@example.com", subject="제목", body_html="<p>본문</p>")


def test_send_report_email_strips_whitespace_from_env_values(monkeypatch):
    # .env에 값을 붙여넣을 때 앞뒤 공백/개행이 섞여 들어가기 쉽고, 그러면
    # 자격증명 자체는 맞아도 헤더 값이 미묘하게 달라져 401이 나는 흔한
    # 원인이라 방어적으로 strip해야 한다.
    _set_full_config(
        monkeypatch,
        MAIL_API_TOKEN="  test-token\n",
        MAIL_API_SYSTEM_ID=" sys-123 ",
        MAIL_API_USER_ID="user-456\n",
    )

    captured = {}

    def _fake_post(url, params=None, headers=None, files=None, timeout=None, proxies=None):
        captured["params"] = params
        captured["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr("ai_friendly_doc.web.mailer.requests.post", _fake_post)

    send_report_email("someone@example.com", subject="제목", body_html="<p>본문</p>")

    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["headers"]["System-ID"] == "sys-123"
    assert captured["params"] == {"userID": "user-456"}


def test_send_report_email_no_proxy_forces_proxies_none(monkeypatch):
    # MAIL_API_NO_PROXY=true면 환경변수 프록시(HTTP_PROXY/HTTPS_PROXY)가
    # 이 사내 API 호출을 제대로 못 넘겨서(예: 502) 실패하는 경우를 위해,
    # 이 호출만 프록시를 건너뛰도록 강제해야 한다.
    _set_full_config(monkeypatch, MAIL_API_NO_PROXY="true")

    captured = {}

    def _fake_post(url, params=None, headers=None, files=None, timeout=None, proxies=None):
        captured["proxies"] = proxies
        return _FakeResponse()

    monkeypatch.setattr("ai_friendly_doc.web.mailer.requests.post", _fake_post)

    send_report_email("someone@example.com", subject="제목", body_html="<p>본문</p>")

    assert captured["proxies"] == {"http": None, "https": None}


def test_send_report_email_no_proxy_false_keeps_default_behavior(monkeypatch):
    _set_full_config(monkeypatch, MAIL_API_NO_PROXY="false")

    captured = {}

    def _fake_post(url, params=None, headers=None, files=None, timeout=None, proxies=None):
        captured["proxies"] = proxies
        return _FakeResponse()

    monkeypatch.setattr("ai_friendly_doc.web.mailer.requests.post", _fake_post)

    send_report_email("someone@example.com", subject="제목", body_html="<p>본문</p>")

    assert captured["proxies"] is None


def test_send_report_email_no_proxy_bypasses_real_proxy_env_var(monkeypatch):
    # 실제 requests 동작으로 검증: 존재하지 않는 프록시 주소를 HTTPS_PROXY로
    # 심어두면, 프록시를 실제로 타는 경우 연결 실패로 확실히 구분된다.
    # MAIL_API_NO_PROXY=true일 때는 이 가짜 프록시를 무시하고 로컬 페이크
    # 서버에 직접 도달해야 한다.
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received["hit"] = True
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"mailId":"mail-1"}')

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _set_full_config(
            monkeypatch,
            MAIL_API_NO_PROXY="true",
            MAIL_API_BASE_URL=f"http://127.0.0.1:{port}",
        )
        # 존재하지 않는 프록시 주소 - 실제로 이걸 타면 연결 자체가 실패한다.
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")

        send_report_email("someone@example.com", subject="제목", body_html="<p>본문</p>")

        assert received.get("hit") is True
    finally:
        server.shutdown()


def test_send_report_email_raises_on_network_error(monkeypatch):
    _set_full_config(monkeypatch)

    def _raise(*args, **kwargs):
        raise requests.ConnectionError("연결 실패")

    monkeypatch.setattr("ai_friendly_doc.web.mailer.requests.post", _raise)

    with pytest.raises(MailConfigError, match="연결 실패"):
        send_report_email("someone@example.com", subject="제목", body_html="<p>본문</p>")


def test_send_report_email_succeeds_even_if_response_body_not_json(monkeypatch):
    class _NonJsonResponse(_FakeResponse):
        def json(self):
            raise ValueError("not json")

    _set_full_config(monkeypatch)
    monkeypatch.setattr("ai_friendly_doc.web.mailer.requests.post", lambda *a, **k: _NonJsonResponse())

    send_report_email("someone@example.com", subject="제목", body_html="<p>본문</p>")
