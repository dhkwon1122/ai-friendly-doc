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
    def __init__(self, status_code=200, json_body=None):
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {"mailId": "mail-1"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

    def json(self):
        return self._json_body


def test_send_report_email_posts_multipart_mail_part(monkeypatch):
    _set_full_config(monkeypatch, MAIL_API_SENDER_ADDRESS="bot@example.com")

    captured = {}

    def _fake_post(url, params=None, headers=None, files=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["files"] = files
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("ai_friendly_doc.web.mailer.requests.post", _fake_post)

    send_report_email("someone@example.com", subject="분석 리포트", body_html="<p>본문 내용</p>")

    assert captured["url"] == "https://openapi.samsung.net/mail/api/v2.0/mails/send"
    assert captured["params"] == {"userID": "user-456"}
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["headers"]["System-ID"] == "sys-123"

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

    def _fake_post(url, params=None, headers=None, files=None, timeout=None):
        return _FakeResponse()

    captured_payload = {}

    def _capturing_post(url, params=None, headers=None, files=None, timeout=None):
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
