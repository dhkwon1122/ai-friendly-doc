"""환경변수 기반 설정 로더."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """필수 설정 값이 없을 때 발생."""


@dataclass(frozen=True)
class ConfluenceConfig:
    base_url: str
    auth_type: str  # "basic" (Cloud: email + api token) | "bearer" (Server/DC: PAT)
    email: str | None
    api_token: str

    @property
    def api_root(self) -> str:
        return f"{self.base_url.rstrip('/')}/rest/api"


def load_confluence_config() -> ConfluenceConfig:
    load_dotenv()

    base_url = os.environ.get("CONFLUENCE_BASE_URL")
    api_token = os.environ.get("CONFLUENCE_API_TOKEN")
    auth_type = os.environ.get("CONFLUENCE_AUTH_TYPE", "basic")
    email = os.environ.get("CONFLUENCE_EMAIL")

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
    if auth_type == "basic" and not email:
        raise ConfigError("CONFLUENCE_AUTH_TYPE=basic 인 경우 CONFLUENCE_EMAIL이 필요합니다.")

    return ConfluenceConfig(
        base_url=base_url,
        auth_type=auth_type,
        email=email,
        api_token=api_token,
    )
