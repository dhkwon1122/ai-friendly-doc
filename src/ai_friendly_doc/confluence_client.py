"""Confluence REST API 읽기 전용 클라이언트.

쓰기 API는 의도적으로 제공하지 않는다. 이 도구는 원본 문서를 수정하지 않고
개선 제안 리포트만 생성한다.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Iterator

import requests
import urllib3

from .config import ConfluenceConfig

_logger = logging.getLogger(__name__)

# 일부 사내 Confluence는 앞단 WAF/게이트웨이가 브라우저처럼 보이지 않는
# 요청(파이썬 requests의 기본 User-Agent 등)을 차단한다 - 자격증명이 맞아도
# 브라우저에서는 되고 이 클라이언트로는 403이 나는 대표적인 원인이다. 흔히
# 통하는 일반 브라우저 UA를 기본값으로 쓰고, 그래도 안 되면 환경변수로
# 실제 브라우저의 UA를 그대로 넣어볼 수 있게 한다.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class ConfluencePage:
    id: str
    title: str
    space_key: str
    version: int
    storage_html: str
    web_url: str


class ConfluenceClient:
    def __init__(self, config: ConfluenceConfig, session: requests.Session | None = None):
        self._config = config
        self._session = session or requests.Session()
        self._session.verify = config.verify_ssl
        if not config.verify_ssl:
            # 사내 서버가 자체 서명 인증서를 쓰는 경우 검증을 끄되, urllib3의
            # InsecureRequestWarning이 요청마다 쏟아지는 것은 막는다.
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # 계정 ID + 비밀번호로 HTTP Basic Auth. API 토큰/PAT 기반 인증은
        # 지원하지 않는다 (사내 환경에서 토큰 방식이 막혀 있어 ID/비밀번호만 씀).
        self._session.auth = (config.email, config.api_token)
        self._session.headers["User-Agent"] = os.environ.get("CONFLUENCE_USER_AGENT") or DEFAULT_USER_AGENT

    def get_page(self, page_id: str) -> ConfluencePage:
        resp = self._session.get(
            f"{self._config.api_root}/content/{page_id}",
            params={"expand": "body.storage,version,space"},
        )
        self._raise_for_status(resp)
        return self._to_page(resp.json())

    def iter_space_pages(self, space_key: str, page_size: int = 25) -> Iterator[ConfluencePage]:
        start = 0
        while True:
            resp = self._session.get(
                f"{self._config.api_root}/content",
                params={
                    "spaceKey": space_key,
                    "type": "page",
                    "status": "current",
                    "expand": "body.storage,version,space",
                    "start": start,
                    "limit": page_size,
                },
            )
            self._raise_for_status(resp)
            data = resp.json()
            results = data.get("results", [])
            for raw in results:
                yield self._to_page(raw)
            if data.get("size", 0) < page_size or not results:
                break
            start += page_size

    def _raise_for_status(self, resp: requests.Response) -> None:
        """resp.raise_for_status()를 그대로 쓰면 상태 코드/URL만 남고 응답
        본문은 사라진다. WAF나 게이트웨이가 막은 경우 본문에 실제 차단
        사유(예: "IP not allowed", "User-Agent not permitted" 등)가 있는
        경우가 많아서, 있으면 에러 메시지에 그대로 붙여준다 - 서버 로그를
        따로 안 봐도 사용자가 원인을 바로 알 수 있도록.
        """
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            body_preview = (resp.text or "").strip()[:500]
            _logger.warning("Confluence 요청 실패: %s | 응답 본문: %s", e, body_preview)
            if body_preview:
                raise requests.HTTPError(f"{e} | 응답 본문: {body_preview}", response=resp) from e
            raise

    def _to_page(self, raw: dict) -> ConfluencePage:
        page_id = raw["id"]
        space_key = raw.get("space", {}).get("key", "")
        webui = raw.get("_links", {}).get("webui", "")
        base = raw.get("_links", {}).get("base", self._config.base_url)
        return ConfluencePage(
            id=page_id,
            title=raw["title"],
            space_key=space_key,
            version=raw.get("version", {}).get("number", 0),
            storage_html=raw.get("body", {}).get("storage", {}).get("value", ""),
            web_url=f"{base}{webui}" if webui else "",
        )
