"""Confluence REST API 읽기 전용 클라이언트.

쓰기 API는 의도적으로 제공하지 않는다. 이 도구는 원본 문서를 수정하지 않고
개선 제안 리포트만 생성한다.

인증은 Personal Access Token(PAT) 기반 Bearer 인증만 지원한다. 계정
ID/비밀번호로 하는 HTTP Basic Auth는 지원하지 않는다 - 다수의 사내
Confluence Server/DC 인스턴스가 관리자 설정으로 Basic Auth 자체를 꺼두고
("Basic Authentication has been disabled on this instance") PAT/SSO만
허용하기 때문에, 자격증명이 맞아도 Basic Auth 요청은 무조건 거부된다.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
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
class Attachment:
    filename: str
    download_url: str


@dataclass(frozen=True)
class ConfluencePage:
    id: str
    title: str
    space_key: str
    version: int
    storage_html: str
    web_url: str
    # 이 페이지에 첨부된 파일 목록(이미지 포함) - 본문에 이미지가 있을 때
    # 원본을 그대로 새 페이지에 옮길 방법이 없어서(쓰기 API 미제공), 대신
    # 사람이 직접 다운로드해서 다시 첨부할 수 있게 실제 다운로드 링크를
    # 만드는 데 쓴다. 기본값을 빈 리스트로 둬서 이 필드를 몰라도 되는
    # 기존 호출부(테스트 등)가 계속 동작하게 한다.
    attachments: list[Attachment] = field(default_factory=list)


class ConfluenceClient:
    def __init__(self, config: ConfluenceConfig, session: requests.Session | None = None):
        self._config = config
        self._session = session or requests.Session()
        self._session.verify = config.verify_ssl
        if not config.verify_ssl:
            # 사내 서버가 자체 서명 인증서를 쓰는 경우 검증을 끄되, urllib3의
            # InsecureRequestWarning이 요청마다 쏟아지는 것은 막는다.
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # Personal Access Token(PAT) 기반 Bearer 인증. 계정 ID + 비밀번호로 하는
        # Basic Auth는 쓰지 않는다 - 위 모듈 docstring 참고. 토큰 앞뒤 공백/개행은
        # 복사-붙여넣기 과정에서 섞여 들어가기 쉽고, 그러면 자격증명 자체는
        # 맞아도 Authorization 헤더 값이 미묘하게 달라져 401이 난다 - 방어적으로
        # strip한다.
        self._session.headers["Authorization"] = f"Bearer {config.api_token.strip()}"
        # 일부 사내 게이트웨이는 Accept 헤더가 없으면 REST API 대신 브라우저용
        # 로그인/HTML 흐름으로 요청을 취급해 인증 결과가 달라진다 - 명시적으로
        # JSON을 요구한다.
        self._session.headers["Accept"] = "application/json"
        self._session.headers["User-Agent"] = os.environ.get("CONFLUENCE_USER_AGENT") or DEFAULT_USER_AGENT

    def get_page(self, page_id: str) -> ConfluencePage:
        resp = self._session.get(
            f"{self._config.api_root}/content/{page_id}",
            params={"expand": "body.storage,version,space,children.attachment"},
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
                    "expand": "body.storage,version,space,children.attachment",
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

        403이 "PAT은 맞는데 이 앱만 막힘"인지 "저장된 토큰 자체가 기대와
        다름/비어 있음"(예: 예전 방식으로 저장해둔 값을 재저장하지 않고 그대로
        쓰는 경우)인지 헷갈리기 쉬워서, 실제로 어떤 base_url로 요청했는지와
        토큰이 비어있지 않은지(길이만)도 같이 보여준다 - 토큰 값 자체는 당연히
        포함하지 않는다.
        """
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            body_preview = (resp.text or "").strip()[:500]
            token_len = len(self._config.api_token or "")
            context = f"(base_url: {self._config.base_url!r}, PAT 길이: {token_len})"
            _logger.warning("Confluence 요청 실패: %s %s | 응답 본문: %s", e, context, body_preview)
            message = f"{e} {context}"
            if body_preview:
                message += f" | 응답 본문: {body_preview}"
            raise requests.HTTPError(message, response=resp) from e

    def _to_page(self, raw: dict) -> ConfluencePage:
        page_id = raw["id"]
        space_key = raw.get("space", {}).get("key", "")
        webui = raw.get("_links", {}).get("webui", "")
        # API 응답의 _links.base는 API 게이트웨이 주소를 가리키는 경우가
        # 흔해서(REST 호출에 쓴 base_url과 같은 값이거나 아예 그 값을 그대로
        # 돌려주기도 함) 원본 문서 링크로 쓰기에 부적절할 수 있다 - 설정된
        # web_base_url(사람이 브라우저로 보는 주소)을 항상 우선한다.
        base = self._config.web_base_url
        return ConfluencePage(
            id=page_id,
            title=raw["title"],
            space_key=space_key,
            version=raw.get("version", {}).get("number", 0),
            storage_html=raw.get("body", {}).get("storage", {}).get("value", ""),
            web_url=f"{base}{webui}" if webui else "",
            attachments=self._parse_attachments(raw, base),
        )

    def _parse_attachments(self, raw: dict, base: str) -> list[Attachment]:
        # expand=children.attachment로 같이 받아온 첨부파일 목록에서
        # 파일명과 실제 다운로드 링크(_links.download, base 기준 상대
        # 경로)를 뽑아낸다. 원본 문서 링크와 마찬가지로 API 게이트웨이가
        # 아니라 사람이 브라우저로 접속하는 web_base_url을 기준으로 절대
        # 경로를 만든다.
        results = raw.get("children", {}).get("attachment", {}).get("results", [])
        attachments = []
        for item in results:
            filename = item.get("title")
            download_href = item.get("_links", {}).get("download")
            if not filename or not download_href:
                continue
            attachments.append(Attachment(filename=filename, download_url=f"{base}{download_href}"))
        return attachments
