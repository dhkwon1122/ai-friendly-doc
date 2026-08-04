"""Confluence REST API 읽기 전용 클라이언트.

쓰기 API는 의도적으로 제공하지 않는다. 이 도구는 원본 문서를 수정하지 않고
개선 제안 리포트만 생성한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import requests

from .config import ConfluenceConfig


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
        if config.auth_type == "basic":
            self._session.auth = (config.email, config.api_token)
        elif config.auth_type == "bearer":
            self._session.headers["Authorization"] = f"Bearer {config.api_token}"
        else:
            raise ValueError(f"지원하지 않는 CONFLUENCE_AUTH_TYPE: {config.auth_type}")

    def get_page(self, page_id: str) -> ConfluencePage:
        resp = self._session.get(
            f"{self._config.api_root}/content/{page_id}",
            params={"expand": "body.storage,version,space"},
        )
        resp.raise_for_status()
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
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            for raw in results:
                yield self._to_page(raw)
            if data.get("size", 0) < page_size or not results:
                break
            start += page_size

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
