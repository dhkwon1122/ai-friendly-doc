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


@dataclass(frozen=True)
class ConfluenceConfig:
    base_url: str
    email: str  # 계정 ID (Server/DC는 로그인 ID, Cloud는 이메일)
    api_token: str  # 비밀번호. HTTP Basic Auth로 (email, api_token)을 그대로 보낸다.
    verify_ssl: bool = True  # 사내 서버가 자체 서명 인증서를 쓰면 False로 (신뢰 가능한 네트워크에서만 끌 것)

    @property
    def api_root(self) -> str:
        return f"{self.base_url.rstrip('/')}/rest/api"


def load_confluence_config() -> ConfluenceConfig:
    load_dotenv()

    base_url = os.environ.get("CONFLUENCE_BASE_URL")
    email = os.environ.get("CONFLUENCE_EMAIL")
    api_token = os.environ.get("CONFLUENCE_API_TOKEN")

    missing = [
        name
        for name, value in [
            ("CONFLUENCE_BASE_URL", base_url),
            ("CONFLUENCE_EMAIL", email),
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

    return ConfluenceConfig(
        base_url=base_url,
        email=email,
        api_token=api_token,
        verify_ssl=verify_ssl,
    )
