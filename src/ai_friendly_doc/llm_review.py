"""LLM(사내 vLLM 등 OpenAI 호환 API)을 이용한 심층 문서 검토.

규칙 엔진(rules/)이 구조적인 문제(제목 계층, 표 헤더, alt 텍스트 등)를
잡는다면, 이 모듈은 실제 내용을 LLM에게 읽혀서 세 가지를 한다:

1. 규칙 엔진이 잡지 못하는 문제(모호한 지시어, 설명 없는 사내 용어, 생략된
   전제, 불명확한 결론 등)를 새로 찾는다.
2. 규칙 엔진이 이미 찾은 문제들에 대해, 그냥 조언이 아니라 문서에 바로
   복사해서 붙여넣을 수 있는 실제 수정 텍스트를 만들어 채워준다. (규칙
   엔진은 "표에 헤더가 없다"는 사실은 알지만 실제로 어떤 문구를 채워야
   하는지는 모르고, LLM은 문서 내용을 읽었으니 채울 수 있다.)
3. 위 1, 2번을 모두 반영한, 문서 전체의 수정본(revised_document)을 만든다.
   웹 UI에서 원본과 나란히 보여주는 데 쓴다.

LLM_BASE_URL이 설정된 경우에만 동작하며, analyzer.analyze_page()가
설정 여부를 보고 자동으로 호출한다.
"""

from __future__ import annotations

import dataclasses
import json
import os

from bs4 import BeautifulSoup, Tag
from openai import OpenAI

from .confluence_client import ConfluencePage
from .guidelines import GUIDELINES, GUIDELINES_BY_ID
from .rules import Severity, Suggestion

DEFAULT_MAX_INPUT_CHARS = 12000
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_OUTPUT_TOKENS = 4096  # 문서 전체 수정본까지 만들어야 해서 넉넉하게

_HEADING_LEVELS = {f"h{i}": i for i in range(1, 7)}

# 이 셋에 속한 가이드라인은 규칙 엔진이 원본 HTML(colspan/매크로/스타일 태그 등)로
# 이미 판별하는데, LLM에게는 그 정보가 다 빠진 평문만 전달되기 때문에(아래
# storage_html_to_plain_text 참고) LLM에게 새로 찾아달라고 요청하지는 않는다.
# (다만 이 가이드라인에 해당하는 규칙 위반이라도, rule_fixes를 통한 구체적인
# 수정 텍스트 생성 요청 대상에서는 제외하지 않는다 - 예를 들어 표 병합 문제
# 자체는 LLM이 새로 "찾을" 수 없지만, 규칙이 이미 찾아준 뒤 "이 표를 어떻게
# 다시 쓰면 좋을지"는 LLM이 문서 내용을 보고 제안할 수 있다.)
_LLM_INVISIBLE_GUIDELINE_IDS = {"extra-2", "extra-3", "extra-7"}


def _guideline_checklist() -> str:
    lines = [f"- {g.id}: {g.label}" for g in GUIDELINES if g.id not in _LLM_INVISIBLE_GUIDELINE_IDS]
    return "\n".join(lines)


SYSTEM_PROMPT = f"""\
당신은 사내 Confluence 문서를 검토해서, AI 에이전트나 RAG 시스템이 이 문서 \
"만" 읽고도 정확하게 이해하고 활용할 수 있는지를 평가하는 전문가입니다.

이 조직은 다음과 같은 "AI-friendly 문서 작성 가이드라인"을 정해두었습니다:

{_guideline_checklist()}

사용자 메시지에는 문서 본문이 주어지고, 이미 구조 검사(규칙 엔진)로 발견된
문제 목록이 번호와 함께 같이 주어질 수 있습니다. 다음 세 가지를 모두
수행하세요:

1. **새 문제 찾기**: 위 가이드라인 관점에서, 아직 목록에 없는 문제를 새로
   찾으세요. 이 목록에 명확히 해당하지 않아도 AI가 이 문서를 오독하거나
   잘못 요약할 만한 문제라면 함께 지적하세요(그 경우 guideline은 "other").
2. **기존 문제에 대한 실제 수정안 작성**: 주어진 기존 문제 목록의 각 항목에
   대해, 조언이 아니라 문서에 그대로 복사해서 붙여넣을 수 있는 실제 수정
   텍스트를 작성하세요. 문서에 실제로 있는 정보(제목, 본문 내용, 이미지
   파일명, 표의 다른 셀 값 등)를 최대한 활용해서 구체적으로 채우세요.
   확실히 알 수 없는 부분(예: 이미지의 실제 내용, 정확한 날짜)은 문서 안의
   단서로 최선을 다해 추정하고, 추정이라는 것을 짧게 표시하세요
   (예: "(파일명 기준 추정, 확인 필요)").
3. **문서 전체 수정본 작성**: 위 1, 2번에서 만든 새 발견 사항과 수정안을
   모두 반영해서, 문서 처음부터 끝까지 완전히 다시 쓴 수정본을 만드세요.
   원본과 같은 평문 형식(제목은 #/##/###, 표는 | a | b |, 목록은 -)을
   유지하고, 문제가 없던 부분은 그대로 두세요.

새로 찾은 문제는 다음 필드를 가진 객체로 만드세요. "suggestion"은 조언이
아니라 실제로 붙여넣을 수 있는 구체적인 문구/문장이어야 합니다:
{{"severity": "info" | "warning" | "critical",
 "location": "어느 부분에 대한 지적인지 (섹션/문단을 짧게 인용하거나 설명)",
 "message": "무엇이 문제인지",
 "suggestion": "실제로 붙여넣을 수 있는 구체적인 수정 문구/문장",
 "guideline": "위 목록의 id 중 가장 관련 있는 것 (예: \\"core-1\\"), 없으면 \\"other\\""}}

기존 문제에 대한 수정안은 다음 필드를 가진 객체로 만드세요:
{{"index": 기존 문제 목록에 표시된 번호(정수),
 "fix": "실제로 붙여넣을 수 있는 구체적인 수정 텍스트"}}

다음 JSON 객체 형식으로만 답하세요. 다른 설명이나 코드펜스 없이 이 객체만
출력합니다:
{{"new_findings": [...], "rule_fixes": [...], "revised_document": "문서 전체 수정본"}}

찾은 문제나 만들 수정안이 없으면 해당 배열을 빈 배열로 두되, revised_document는
항상 채우세요 (고칠 게 없으면 원본과 같은 내용을 그대로 넣으면 됩니다).
"""


class LLMReviewError(RuntimeError):
    """LLM 호출/응답 처리 중 문제가 생겼을 때 발생."""


@dataclasses.dataclass
class LLMReviewResult:
    suggestions: list[Suggestion]
    # 문서 전체에 새 발견/수정안을 반영해 다시 쓴 평문. LLM이 안 만들었거나
    # LLM 자체가 설정 안 돼 있으면 None (원본 문서는 별도로 항상 존재함).
    revised_document: str | None


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
                lines.append(_image_line(child, name))
            else:
                walk(child)

    walk(soup)
    text = "\n".join(lines).strip()
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + "\n\n...(문서가 길어 이하 생략됨)"
    return text


def _image_line(el: Tag, name: str) -> str:
    alt = el.get("ac:alt") or el.get("alt") or ""
    if alt:
        return f"[이미지: {alt}]"
    filename = None
    filename_el = el.find(["ri:attachment", "ri:url"])
    if filename_el is not None:
        filename = filename_el.get("ri:filename") or filename_el.get("ri:value")
    elif name == "img":
        filename = el.get("src")
    marker = f", 파일명: {filename}" if filename else ""
    return f"[이미지 (대체 텍스트 없음{marker})]"


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


def _parse_llm_response(raw: str) -> dict:
    """{"new_findings": [...], "rule_fixes": [...], "revised_document": "..."} 형태의
    JSON 객체를 파싱한다."""
    text = _strip_code_fence(raw)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise LLMReviewError(f"LLM 응답을 JSON으로 해석하지 못했습니다: {raw[:200]!r}") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise LLMReviewError(f"LLM 응답을 JSON으로 해석하지 못했습니다: {raw[:200]!r}") from e

    if not isinstance(data, dict):
        raise LLMReviewError("LLM 응답이 예상한 JSON 객체 형식이 아닙니다.")

    new_findings = data.get("new_findings", [])
    rule_fixes = data.get("rule_fixes", [])
    if not isinstance(new_findings, list) or not isinstance(rule_fixes, list):
        raise LLMReviewError("LLM 응답의 new_findings/rule_fixes가 배열 형식이 아닙니다.")

    revised_document = data.get("revised_document")
    if revised_document is not None and not isinstance(revised_document, str):
        raise LLMReviewError("LLM 응답의 revised_document가 문자열 형식이 아닙니다.")

    return {"new_findings": new_findings, "rule_fixes": rule_fixes, "revised_document": revised_document}


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


def _apply_rule_fixes(rule_suggestions: list[Suggestion], fixes: list[dict]) -> list[Suggestion]:
    """LLM이 만든 구체적 수정안을 인덱스로 매칭해 규칙 기반 Suggestion에 채워 넣는다.

    매칭 안 된 항목은 원래의(조언 형태) suggestion을 그대로 유지한다.
    """
    fix_by_index: dict[int, str] = {}
    for item in fixes:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        fix_text = item.get("fix")
        if isinstance(fix_text, str) and fix_text.strip():
            fix_by_index[idx] = fix_text.strip()

    updated = []
    for i, s in enumerate(rule_suggestions):
        fix_text = fix_by_index.get(i)
        updated.append(dataclasses.replace(s, suggestion=fix_text) if fix_text else s)
    return updated


def _build_user_content(page: ConfluencePage, text: str, rule_suggestions: list[Suggestion]) -> str:
    parts = [f"문서 제목: {page.title}", "", text]
    if rule_suggestions:
        parts.append("")
        parts.append("---")
        parts.append("이미 구조 검사로 발견된 문제 목록 (각 항목에 대한 구체적 수정안을 rule_fixes에 담아 응답):")
        for i, s in enumerate(rule_suggestions):
            parts.append(f"{i}. [{s.rule_id}] {s.location}: {s.message}")
    return "\n".join(parts)


def review_with_llm(page: ConfluencePage, rule_suggestions: list[Suggestion] | None = None) -> LLMReviewResult:
    """설정된 LLM으로 페이지 내용을 심층 검토한다.

    rule_suggestions를 넘기면, 그 각각에 대해 LLM이 실제 문서 내용을 참고해
    만든 구체적인(복사-붙여넣기 가능한) 수정안으로 suggestion 필드를 갱신하고,
    거기에 LLM이 새로 찾은 문제들을 더해서 반환한다. rule_suggestions를 안
    넘기면 새로 찾은 문제들만 반환한다 (규칙 없이 LLM 검토만 쓰는 경우).
    거기에 더해 문서 전체를 다시 쓴 수정본(revised_document)도 만든다.

    LLM_BASE_URL이 없으면 rule_suggestions를 그대로(원래 조언 형태로) 담고
    revised_document는 None인 결과를 반환한다. 그 외 설정 누락이나 호출/응답
    실패는 LLMReviewError로 감싸서 던진다 (호출자가 나머지 규칙 기반 결과는
    살리고 이 부분만 실패로 표시할 수 있도록).
    """
    rule_suggestions = rule_suggestions or []

    if not is_llm_configured():
        return LLMReviewResult(suggestions=list(rule_suggestions), revised_document=None)

    model = os.environ.get("LLM_MODEL")
    if not model:
        raise LLMReviewError("LLM_BASE_URL은 설정됐지만 LLM_MODEL이 설정되지 않았습니다.")

    max_chars_raw = os.environ.get("LLM_MAX_INPUT_CHARS")
    max_chars = int(max_chars_raw) if max_chars_raw else DEFAULT_MAX_INPUT_CHARS
    timeout_raw = os.environ.get("LLM_TIMEOUT_SECONDS")
    timeout = float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT_SECONDS
    max_output_tokens_raw = os.environ.get("LLM_MAX_OUTPUT_TOKENS")
    max_output_tokens = int(max_output_tokens_raw) if max_output_tokens_raw else DEFAULT_MAX_OUTPUT_TOKENS

    text = storage_html_to_plain_text(page.storage_html, max_chars=max_chars)
    if not text.strip():
        return LLMReviewResult(suggestions=list(rule_suggestions), revised_document=None)

    user_content = _build_user_content(page, text, rule_suggestions)

    try:
        response = _client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            timeout=timeout,
            max_tokens=max_output_tokens,
        )
    except Exception as e:  # noqa: BLE001 - 원인 그대로 사용자에게 보여줌
        raise LLMReviewError(f"LLM 호출에 실패했습니다: {e}") from e

    raw = response.choices[0].message.content or ""
    data = _parse_llm_response(raw)

    updated_rule_suggestions = _apply_rule_fixes(rule_suggestions, data["rule_fixes"])
    new_findings = _to_suggestions(data["new_findings"])
    revised_document = data["revised_document"] or None

    return LLMReviewResult(suggestions=updated_rule_suggestions + new_findings, revised_document=revised_document)
