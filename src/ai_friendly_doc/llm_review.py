"""LLM(사내 vLLM 등 OpenAI 호환 API)을 이용한 심층 문서 검토.

규칙 엔진(rules/)이 구조적인 문제(제목 계층, 표 헤더, alt 텍스트 등)를
잡는다면, 이 모듈은 실제 내용을 LLM에게 읽혀서 "AI가 이 문서만 보고
정확히 이해할 수 있는가" 관점의 문제(모호한 지시어, 설명 없는 사내
용어, 생략된 전제, 불명확한 결론 등)를 찾아 Suggestion으로 만든다.

LLM_BASE_URL이 설정된 경우에만 동작하며, analyzer.analyze_page()가
설정 여부를 보고 자동으로 호출한다.
"""

from __future__ import annotations

import json
import os

from bs4 import BeautifulSoup, Tag
from openai import OpenAI

from .confluence_client import ConfluencePage
from .guidelines import GUIDELINES, GUIDELINES_BY_ID
from .rules import Severity, Suggestion

DEFAULT_MAX_INPUT_CHARS = 12000
DEFAULT_TIMEOUT_SECONDS = 60.0

_HEADING_LEVELS = {f"h{i}": i for i in range(1, 7)}

# 이 셋에 속한 가이드라인은 규칙 엔진이 원본 HTML(colspan/매크로/스타일 태그 등)로
# 이미 판별하는데, LLM에게는 그 정보가 다 빠진 평문만 전달되기 때문에(아래
# storage_html_to_plain_text 참고) LLM에게 판단해달라고 요청하지 않는다.
_LLM_INVISIBLE_GUIDELINE_IDS = {"extra-2", "extra-3", "extra-7"}


def _guideline_checklist() -> str:
    lines = [f"- {g.id}: {g.label}" for g in GUIDELINES if g.id not in _LLM_INVISIBLE_GUIDELINE_IDS]
    return "\n".join(lines)


SYSTEM_PROMPT = f"""\
당신은 사내 Confluence 문서를 검토해서, AI 에이전트나 RAG 시스템이 이 문서 \
"만" 읽고도 정확하게 이해하고 활용할 수 있는지를 평가하는 전문가입니다.

이 조직은 다음과 같은 "AI-friendly 문서 작성 가이드라인"을 정해두었습니다.
문서를 읽으며 이 가이드라인들을 기준으로 위반 사항을 찾으세요:

{_guideline_checklist()}

이 목록에 명확히 해당하지 않아도, AI가 이 문서를 오독하거나 잘못 요약할 만한
문제라면 함께 지적하세요(그 경우 guideline은 "other"로 남기세요).

각 문제를 JSON 배열로만 답하세요. 다른 설명이나 코드펜스 없이 배열만 출력합니다.
배열의 각 항목은 다음 필드를 가진 객체입니다:
{{"severity": "info" | "warning" | "critical",
 "location": "어느 부분에 대한 지적인지 (섹션/문단을 짧게 인용하거나 설명)",
 "message": "무엇이 문제인지",
 "suggestion": "구체적으로 어떻게 고치면 좋을지. 가능하면 고친 예시 문장을 포함",
 "guideline": "위 목록의 id 중 가장 관련 있는 것 (예: \\"core-1\\"), 없으면 \\"other\\""}}

문제가 없으면 빈 배열 []을 반환하세요.
"""


class LLMReviewError(RuntimeError):
    """LLM 호출/응답 처리 중 문제가 생겼을 때 발생."""


def is_llm_configured() -> bool:
    return bool(os.environ.get("LLM_BASE_URL"))


def _client() -> OpenAI:
    base_url = os.environ.get("LLM_BASE_URL")
    api_key = os.environ.get("LLM_API_KEY") or "not-needed"
    return OpenAI(base_url=base_url, api_key=api_key)


def storage_html_to_plain_text(storage_html: str, max_chars: int | None = DEFAULT_MAX_INPUT_CHARS) -> str:
    """Confluence storage format(XHTML)을 LLM 프롬프트에 넣기 좋은 평문으로 바꾼다.

    parser.py의 ParsedDoc과 달리 카테고리별로 나뉘지 않고 문서에 등장하는
    순서 그대로 이어붙인 텍스트를 만든다 (LLM이 글의 흐름을 볼 수 있도록).
    """
    soup = BeautifulSoup(storage_html, "html.parser")
    lines: list[str] = []

    def walk(node: Tag) -> None:
        for child in node.children:
            name = getattr(child, "name", None)
            if name is None:
                continue
            if name in _HEADING_LEVELS:
                text = child.get_text(strip=True)
                if text:
                    lines.append(f"\n{'#' * _HEADING_LEVELS[name]} {text}\n")
            elif name == "p":
                text = child.get_text(strip=True)
                if text:
                    lines.append(text)
            elif name in ("ul", "ol"):
                for li in child.find_all("li", recursive=False):
                    text = li.get_text(strip=True)
                    if text:
                        lines.append(f"- {text}")
            elif name == "table":
                for row in child.find_all("tr"):
                    cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
                    if any(cells):
                        lines.append("| " + " | ".join(cells) + " |")
            elif name in ("ac:image", "img"):
                alt = child.get("ac:alt") or child.get("alt") or ""
                lines.append(f"[이미지{': ' + alt if alt else ' (대체 텍스트 없음)'}]")
            else:
                walk(child)

    walk(soup)
    text = "\n".join(lines).strip()
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + "\n\n...(문서가 길어 이하 생략됨)"
    return text


def _parse_llm_json(raw: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise LLMReviewError(f"LLM 응답을 JSON으로 해석하지 못했습니다: {raw[:200]!r}") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise LLMReviewError(f"LLM 응답을 JSON으로 해석하지 못했습니다: {raw[:200]!r}") from e

    if not isinstance(data, list):
        raise LLMReviewError("LLM 응답이 예상한 JSON 배열 형식이 아닙니다.")
    return data


def _to_suggestions(items: list[dict]) -> list[Suggestion]:
    suggestions = []
    for item in items:
        if not isinstance(item, dict):
            continue
        severity_raw = str(item.get("severity", "info")).strip().lower()
        severity = severity_raw if severity_raw in ("info", "warning", "critical") else "info"
        guideline_raw = str(item.get("guideline") or "").strip()
        guideline_id = guideline_raw if guideline_raw in GUIDELINES_BY_ID else None
        suggestions.append(
            Suggestion(
                rule_id="llm-review",
                severity=Severity(severity),
                location=str(item.get("location") or "문서 전체"),
                message=str(item.get("message") or ""),
                suggestion=str(item.get("suggestion") or ""),
                guideline_id=guideline_id,
            )
        )
    return suggestions


def review_with_llm(page: ConfluencePage) -> list[Suggestion]:
    """설정된 LLM으로 페이지 내용을 심층 검토해 Suggestion 목록을 반환한다.

    LLM_BASE_URL이 없으면 빈 목록을 반환한다. 그 외 설정 누락이나 호출/응답
    실패는 LLMReviewError로 감싸서 던진다 (호출자가 나머지 규칙 기반 결과는
    살리고 이 부분만 실패로 표시할 수 있도록).
    """
    if not is_llm_configured():
        return []

    model = os.environ.get("LLM_MODEL")
    if not model:
        raise LLMReviewError("LLM_BASE_URL은 설정됐지만 LLM_MODEL이 설정되지 않았습니다.")

    max_chars_raw = os.environ.get("LLM_MAX_INPUT_CHARS")
    max_chars = int(max_chars_raw) if max_chars_raw else DEFAULT_MAX_INPUT_CHARS
    timeout_raw = os.environ.get("LLM_TIMEOUT_SECONDS")
    timeout = float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT_SECONDS

    text = storage_html_to_plain_text(page.storage_html, max_chars=max_chars)
    if not text.strip():
        return []

    try:
        response = _client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"문서 제목: {page.title}\n\n{text}"},
            ],
            temperature=0.2,
            timeout=timeout,
        )
    except Exception as e:  # noqa: BLE001 - 원인 그대로 사용자에게 보여줌
        raise LLMReviewError(f"LLM 호출에 실패했습니다: {e}") from e

    raw = response.choices[0].message.content or ""
    items = _parse_llm_json(raw)
    return _to_suggestions(items)
