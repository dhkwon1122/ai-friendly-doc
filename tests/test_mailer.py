import email
import email.header

import pytest

from ai_friendly_doc.web.mailer import MailConfigError, is_mail_configured, send_report_email


def test_is_mail_configured_false_when_smtp_host_unset(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert is_mail_configured() is False


def test_is_mail_configured_true_when_smtp_host_set(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    assert is_mail_configured() is True


def test_send_report_email_raises_when_smtp_host_missing(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with pytest.raises(MailConfigError, match="SMTP_HOST"):
        send_report_email("someone@example.com", subject="제목", body="본문")


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args = None
        self.sent = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def sendmail(self, from_addr, to_addrs, message):
        self.sent = (from_addr, to_addrs, message)


@pytest.fixture(autouse=True)
def _reset_fake_smtp():
    _FakeSMTP.instances.clear()
    yield
    _FakeSMTP.instances.clear()


def test_send_report_email_sends_via_smtp(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USERNAME", "bot")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "bot@example.com")
    monkeypatch.setattr("ai_friendly_doc.web.mailer.smtplib.SMTP", _FakeSMTP)

    send_report_email("someone@example.com", subject="분석 리포트", body="본문 내용")

    assert len(_FakeSMTP.instances) == 1
    fake = _FakeSMTP.instances[0]
    assert fake.host == "smtp.example.com"
    assert fake.port == 2525
    assert fake.started_tls is True
    assert fake.login_args == ("bot", "secret")
    from_addr, to_addrs, message = fake.sent
    assert from_addr == "bot@example.com"
    assert to_addrs == ["someone@example.com"]
    # 한글이 섞이면 MIMEText가 base64로 인코딩하므로, 파싱해서 디코딩한
    # 내용으로 검증한다 (인코딩된 원문 문자열에는 그대로 안 나타남).
    parsed = email.message_from_string(message)
    assert email.header.decode_header(parsed["Subject"])[0][0].decode("utf-8") == "분석 리포트"
    assert parsed.get_payload(decode=True).decode("utf-8") == "본문 내용"


def test_send_report_email_skips_login_when_no_credentials(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.setattr("ai_friendly_doc.web.mailer.smtplib.SMTP", _FakeSMTP)

    send_report_email("someone@example.com", subject="제목", body="본문")

    assert _FakeSMTP.instances[0].login_args is None


def test_send_report_email_skips_starttls_when_disabled(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "false")
    monkeypatch.setattr("ai_friendly_doc.web.mailer.smtplib.SMTP", _FakeSMTP)

    send_report_email("someone@example.com", subject="제목", body="본문")

    assert _FakeSMTP.instances[0].started_tls is False


def test_send_report_email_defaults_from_address_when_unset(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.delenv("SMTP_FROM", raising=False)
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.setattr("ai_friendly_doc.web.mailer.smtplib.SMTP", _FakeSMTP)

    send_report_email("someone@example.com", subject="제목", body="본문")

    from_addr, _, _ = _FakeSMTP.instances[0].sent
    assert from_addr == "ai-friendly-doc@localhost"


def test_send_report_email_wraps_connection_failure(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")

    def _raise(*args, **kwargs):
        raise ConnectionRefusedError("연결 거부")

    monkeypatch.setattr("ai_friendly_doc.web.mailer.smtplib.SMTP", _raise)

    with pytest.raises(MailConfigError, match="연결 거부"):
        send_report_email("someone@example.com", subject="제목", body="본문")
