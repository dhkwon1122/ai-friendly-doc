"""분석 리포트를 사내 메일 발송 REST API로 보내는 기능 (선택).

SMTP가 아니라 사내 메일 API(기본값 openapi.samsung.net)를 REST 호출로
쓴다. 이 API는 파일 첨부를 지원하는 엔드포인트라 첨부 없이 본문만 보낼
때도 multipart/form-data로 "mail"이라는 이름의 파트에 메일 정보를 JSON
으로 실어 보내야 한다 - 그냥 JSON 바디로 POST하면 안 받아준다.

MAIL_API_TOKEN이 설정된 경우에만 동작한다.
"""

from __future__ import annotations

import json
import logging
import os

import requests

_logger = logging.getLogger(__name__)

DEFAULT_MAIL_API_BASE_URL = "https://openapi.samsung.net/mail/api/v2.0"
DEFAULT_TIMEOUT_SECONDS = 30.0


class MailConfigError(RuntimeError):
    """메일 API 설정 누락이나 발송 실패 시 발생."""


def is_mail_configured() -> bool:
    return bool(os.environ.get("MAIL_API_TOKEN"))


def _require_env(name: str) -> str:
    # .env에 값을 붙여넣는 과정에서 앞뒤 공백/개행이 섞여 들어가기 쉽고,
    # 그러면 자격증명 자체는 맞아도 헤더 값이 미묘하게 달라져 401이 나는
    # 흔한 원인이라 방어적으로 strip한다 (Confluence PAT과 동일한 문제).
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise MailConfigError(
            f"{name} 환경변수가 설정되지 않았습니다. .env.example의 메일 API 관련 항목을 참고하세요."
        )
    return value


def send_report_email(to_email: str, subject: str, body_html: str) -> None:
    """body_html(HTML)을 to_email에 보낸다.

    MAIL_API_TOKEN/MAIL_API_SYSTEM_ID/MAIL_API_USER_ID 중 하나라도 없으면
    MailConfigError를 던진다. 호출 자체가 실패해도(네트워크 오류, 4xx/5xx
    응답) 원인을 그대로 담아 MailConfigError로 감싸서 던진다 - 호출자가
    화면에 실패 사유를 보여줄 수 있도록.
    """
    token = _require_env("MAIL_API_TOKEN")
    system_id = _require_env("MAIL_API_SYSTEM_ID")
    user_id = _require_env("MAIL_API_USER_ID")
    sender_address = os.environ.get("MAIL_API_SENDER_ADDRESS") or user_id

    base_url = (os.environ.get("MAIL_API_BASE_URL") or DEFAULT_MAIL_API_BASE_URL).rstrip("/")
    url = f"{base_url}/mails/send"

    mail_payload = {
        "subject": subject,
        "contents": body_html,
        "contentType": "html",
        "docSecuType": "PERSONAL",
        "sender": {"emailAddress": sender_address},
        "recipients": [{"emailAddress": to_email, "recipientType": "TO"}],
    }
    # 첨부 없이 본문만 보낼 때도 "mail" 파트를 실은 multipart/form-data로
    # 보내야 한다. 한글이 섞이므로 인코딩을 명시적으로 UTF-8 바이트로
    # 고정한다 (str로 넘기면 라이브러리가 기본 인코딩을 쓸 수 있어서 깨짐).
    mail_part = json.dumps(mail_payload, ensure_ascii=False).encode("utf-8")

    try:
        response = requests.post(
            url,
            params={"userID": user_id},
            headers={
                "Authorization": f"Bearer {token}",
                "System-ID": system_id,
            },
            files={"mail": (None, mail_part, "application/json;charset=utf-8")},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.HTTPError as e:
        # 상태 코드/URL만으로는 401/403의 실제 원인(토큰 만료, System-ID/userID
        # 불일치 등)을 알 수 없는 경우가 많다 - Confluence 클라이언트와 마찬가지로
        # 응답 본문이 있으면 에러 메시지에 그대로 포함해서 서버 로그 없이도
        # 화면에서 바로 원인을 확인할 수 있게 한다.
        body_preview = (e.response.text or "").strip()[:500] if e.response is not None else ""
        _logger.warning("메일 발송 API 호출 실패: %s | 응답 본문: %s", e, body_preview)
        message = f"이메일 발송에 실패했습니다: {e}"
        if body_preview:
            message += f" | 응답 본문: {body_preview}"
        raise MailConfigError(message) from e
    except requests.RequestException as e:
        _logger.warning("메일 발송 API 호출 실패: %s", e)
        raise MailConfigError(f"이메일 발송에 실패했습니다: {e}") from e

    try:
        mail_id = response.json().get("mailId")
    except ValueError:
        mail_id = None
    _logger.info("메일 발송 성공 (mailId=%s)", mail_id)
