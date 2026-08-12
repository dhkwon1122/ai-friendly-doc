"""환경변수 기반 설정 로더."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """필수 설정 값이 없을 때 발생."""


def parse_bool_env(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in ("false", "0", "no", "off")


# 리포트/이메일에 넣는 "원본 문서 링크"용 기본값. REST API 호출에 쓰는
# CONFLUENCE_BASE_URL과 반드시 같지 않을 수 있다(API 게이트웨이 주소와
# 사람이 브라우저로 보는 주소가 다른 환경이 흔함) - 그래서 별도 설정으로
# 뺐다.
DEFAULT_WEB_BASE_URL = "https://confluence.samsungds.net"


@dataclass(frozen=True)
class ConfluenceConfig:
    base_url: str
    api_token: str  # Personal Access Token(PAT). Authorization: Bearer 헤더로 보낸다.
    verify_ssl: bool = True  # 사내 서버가 자체 서명 인증서를 쓰면 False로 (신뢰 가능한 네트워크에서만 끌 것)
    # 원본 문서 링크(리포트/이메일에 노출)를 만들 때 쓰는 base URL. REST API
    # 호출(base_url)과는 별개로, 사람이 브라우저로 접속하는 주소를 쓴다.
    web_base_url: str = DEFAULT_WEB_BASE_URL

    @property
    def api_root(self) -> str:
        return f"{self.base_url.rstrip('/')}/rest/api"


def load_confluence_config() -> ConfluenceConfig:
    load_dotenv()

    base_url = os.environ.get("CONFLUENCE_BASE_URL")
    api_token = os.environ.get("CONFLUENCE_API_TOKEN")

    missing = [
        name
        for name, value in [
            ("CONFLUENCE_BASE_URL", base_url),
            ("CONFLUENCE_API_TOKEN", api_token),
        ]
        if not value
    ]
    if missing:
        raise ConfigError(
            "다음 환경변수가 설정되지 않았습니다: "
            + ", ".join(missing)
            + " (.env.example 참고)"
        )

    verify_ssl = parse_bool_env(os.environ.get("CONFLUENCE_VERIFY_SSL"), default=True)
    web_base_url = (os.environ.get("CONFLUENCE_WEB_BASE_URL") or DEFAULT_WEB_BASE_URL).rstrip("/")

    return ConfluenceConfig(
        base_url=base_url,
        api_token=api_token,
        verify_ssl=verify_ssl,
        web_base_url=web_base_url,
    )
