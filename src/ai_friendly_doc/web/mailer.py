"""분석 리포트를 이메일로 보내는 기능 (선택).

SMTP_HOST가 설정된 경우에만 동작한다. LLM_BASE_URL/CONFLUENCE_BASE_URL과
마찬가지로 선택 기능이라, 설정 안 돼 있으면 MailConfigError로 명확한
안내 메시지를 준다 (호출자가 화면에 그대로 보여줄 수 있도록).
"""

from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText

from ..config import parse_bool_env


class MailConfigError(RuntimeError):
    """SMTP 설정 누락이나 발송 실패 시 발생."""


def is_mail_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def _from_address() -> str:
    return os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USERNAME") or "ai-friendly-doc@localhost"


def send_report_email(to_email: str, subject: str, body: str) -> None:
    """body(마크다운 텍스트)를 평문 메일로 to_email에 보낸다.

    SMTP_HOST가 없으면 MailConfigError를 던진다. 발송 자체가 실패해도(인증
    실패, 연결 실패 등) 원인을 그대로 담아 MailConfigError로 감싸서 던진다 -
    호출자가 화면에 실패 사유를 보여줄 수 있도록.
    """
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise MailConfigError(
            "SMTP_HOST 환경변수가 설정되지 않았습니다. "
            ".env.example의 SMTP 관련 항목을 참고해 이메일 발송 설정을 추가하세요."
        )

    port_raw = os.environ.get("SMTP_PORT")
    port = int(port_raw) if port_raw else 587
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    use_tls = parse_bool_env(os.environ.get("SMTP_USE_TLS"), default=True)
    from_addr = _from_address()

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            if use_tls:
                server.starttls()
            if username and password:
                server.login(username, password)
            server.sendmail(from_addr, [to_email], msg.as_string())
    except Exception as e:  # noqa: BLE001 - 원인 그대로 사용자에게 보여줌
        raise MailConfigError(f"이메일 발송에 실패했습니다: {e}") from e
