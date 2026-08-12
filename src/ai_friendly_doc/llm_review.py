"""LLM(사내 vLLM 등 OpenAI 호환 API)을 이용한 심층 문서 검토.

규칙 엔진(rules/)이 구조적인 문제(제목 계층, 표 헤더, alt 텍스트 등)를
잡는다면, 이 모듈은 실제 내용을 LLM에게 읽혀서 다음을 한다:

1. 규칙 엔진이 잡지 못하는 문제(모호한 지시어, 설명 없는 사내 용어, 생략된
   전제, 불명확한 결론 등)를 새로 찾는다.
2. 규칙 엔진이 이미 찾은 문제들에 대해, 그냥 조언이 아니라 문서에 바로
   복사해서 붙여넣을 수 있는 실제 수정 텍스트를 만들어 채워준다. (규칙
   엔진은 "표에 헤더가 없다"는 사실은 알지만 실제로 어떤 문구를 채워야
   하는지는 모르고, LLM은 문서 내용을 읽었으니 채울 수 있다.)
3. 위 1, 2번을 모두 반영한, 문서 전체의 수정본(revised_document)을 만든다.
   웹 UI에서 원본과 나란히 보여주는 데 쓴다.

1·2번과 3번은 별도의 LLM 호출로 나뉘어 있다. 3번(전체 문서 재작성)은
출력이 길어서 자기 완결적인(self-hosted) 소형 모델일수록 중간에 잘리거나
망가지기 쉬운데, 한 호출에 다 묶으면 3번이 실패할 때마다 이미 성공한
1·2번 결과까지 통째로 날아간다. 그래서 3번은 별도 호출로 분리해 최선을
다해 시도하되(best-effort), 실패해도 1·2번 결과(suggestions)는 그대로
살리고 revised_document만 None으로 둔다. 다만 실패 사실 자체는 숨기지
않는다 - 실패 사유를 `llm-revision-error` 항목으로 suggestions에 추가하고
서버 로그에도 남겨서(logging.warning), "왜 수정본이 안 만들어졌는지"를
리포트만 보고도 알 수 있게 한다 (예: max_tokens가 모델의 실제 최대
컨텍스트 길이를 넘어서 서버가 요청 자체를 거부한 경우 등).

1·2번 호출은 실패하면(타임아웃, 응답 잘림, 깨진 JSON 등) 규칙 기반
가이드라인 점수 계산에서 LLM 전용 항목들이 전부 "확인 불가"로 표시된다
(guidelines.score_document 참고). 실제 페이지로 반복 테스트하면 규칙
위반이 많아 출력이 길어지거나 그때그때 모델 상태에 따라 이 호출이 가끔
실패할 수 있어서, 같은 문서를 여러 번 분석했을 때 결과가 "준수"와
"확인 불가"를 오가는 것처럼 보일 수 있다. 이를 줄이기 위해 (a) 규칙
위반 개수에 비례해 출력 토큰 예산을 넉넉히 잡고, (b) 실패하면 한 번
재시도하며, (c) temperature를 0으로 둬서 같은 입력에 대한 응답을 최대한
일관되게 만든다.

LLM_BASE_URL이 설정된 경우에만 동작하며, analyzer.analyze_page()가
설정 여부를 보고 자동으로 호출한다.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os

from bs4 import BeautifulSoup, Tag
from openai import OpenAI

from .confluence_client import ConfluencePage
from .guidelines import GUIDELINES, GUIDELINES_BY_ID
from .rules import Severity, Suggestion

_logger = logging.getLogger(__name__)

DEFAULT_MAX_INPUT_CHARS = 12000
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_OUTPUT_TOKENS = 4096  # 찾기/수정안(1번 호출)의 최소 예산. 규칙 위반이 많으면 늘어남 (_findings_max_output_tokens 참고)
FINDINGS_MAX_ATTEMPTS = 2  # 1번 호출(찾기/수정안)이 실패하면 이만큼(최초 시도 포함) 시도한다

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
문제 목록이 번호와 함께 같이 주어질 수 있습니다. 다음 두 가지를 모두
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
{{"new_findings": [...], "rule_fixes": [...]}}

찾은 문제나 만들 수정안이 없으면 해당 배열을 빈 배열로 두면 됩니다.
"""

REVISION_SYSTEM_PROMPT = """\
당신은 사내 Confluence 문서를 AI-friendly 가이드라인에 맞게 고쳐 쓰는
편집자입니다. 사용자 메시지에는 원본 문서 전체와, 반영해야 할 문제/수정안
목록이 함께 주어집니다.

다음 규칙을 지켜 문서 전체를 처음부터 끝까지 다시 쓰세요:
- 목록에 있는 문제와 수정안을 모두 반영합니다.
- 목록에 없는, 문제가 없던 부분은 그대로 유지합니다 (불필요하게 다시
  쓰지 않습니다).
- 원본과 같은 평문 형식(제목은 #/##/###, 표는 | a | b |)을 유지합니다.
- **목록은 원본의 순서 여부를 그대로 보존하세요**: 원본 문서에서 "1. ",
  "2. "처럼 번호가 매겨진 순서 목록(순서/절차가 중요한 단계 목록 등)은
  수정본에서도 반드시 "1. ", "2. ", "3. "처럼 1부터 시작해 번호를 하나씩
  올려가며 씁니다(항목마다 "1."을 반복하면 안 됩니다). 번호가 없던 순서
  없는 목록은 그대로 "- "를 씁니다. 항목을 추가/삭제하지 않는 한 원본의
  항목 순서도 바꾸지 마세요.
- 다른 설명, 인사말, 코드펜스 없이 수정된 문서 본문만 그대로 출력하세요.
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
            elif name == "ul":
                for li in child.find_all("li", recursive=False):
                    text = li.get_text(strip=True)
                    if text:
                        lines.append(f"- {text}")
            elif name == "ol":
                # ol/ul을 둘 다 "- "로 뭉개면 원본이 순서가 있는(번호 매겨진)
                # 목록이었다는 사실 자체가 LLM에게 안 보이게 되고, 그러면
                # 수정본에서 순서 목록이 순서 없는 목록으로 바뀌거나 항목
                # 순서가 흐트러지기 쉽다 - 실제 번호를 그대로 매겨서 원본이
                # 순서가 있었다는 사실과 그 순서를 함께 전달한다.
                items = [li.get_text(strip=True) for li in child.find_all("li", recursive=False)]
                for idx, text in enumerate(items, start=1):
                    if text:
                        lines.append(f"{idx}. {text}")
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
    """{"new_findings": [...], "rule_fixes": [...]} 형태의 JSON 객체를 파싱한다."""
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

    return {"new_findings": new_findings, "rule_fixes": rule_fixes}


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


def _findings_max_output_tokens(rule_suggestions: list[Suggestion]) -> int:
    # rule_fixes 배열은 항목마다 복사-붙여넣기용 수정 텍스트를 채워야 해서,
    # 규칙 위반이 많은(지저분한 실제) 문서일수록 출력이 길어진다. 개수에
    # 비례해 여유를 둔다 (항목당 대략 250토큰 버퍼).
    return max(DEFAULT_MAX_OUTPUT_TOKENS, len(rule_suggestions) * 250 + DEFAULT_MAX_OUTPUT_TOKENS)


def _run_findings_call(model: str, timeout: float, user_content: str, max_output_tokens: int) -> dict:
    """새 문제 찾기/수정안 채우기 LLM 호출을 1회 시도한다. 실패하면(호출 자체
    실패, 응답 잘림, JSON 파싱 실패) LLMReviewError를 던진다 - 호출자가 재시도
    여부를 결정한다."""
    try:
        response = _client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            timeout=timeout,
            max_tokens=max_output_tokens,
        )
    except Exception as e:  # noqa: BLE001 - 원인 그대로 사용자에게 보여줌
        raise LLMReviewError(f"LLM 호출에 실패했습니다: {e}") from e

    choice = response.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise LLMReviewError(
            f"LLM 응답이 최대 토큰({max_output_tokens}) 제한으로 중간에 잘렸습니다. "
            "규칙 위반 수나 발견된 문제가 유난히 많은 문서일 수 있습니다."
        )

    raw = choice.message.content or ""
    return _parse_llm_response(raw)


def _build_revision_user_content(page: ConfluencePage, text: str, suggestions: list[Suggestion]) -> str:
    parts = [f"문서 제목: {page.title}", "", "원본 문서:", text]
    if suggestions:
        parts.append("")
        parts.append("---")
        parts.append("반영해야 할 문제/수정안 목록:")
        for s in suggestions:
            parts.append(f"- {s.location}: {s.message} -> {s.suggestion}")
    return "\n".join(parts)


def _revision_max_output_tokens(text: str) -> int:
    # 문서 전체를 거의 그대로(+ 수정 반영) 다시 써야 해서, 출력 길이가 입력
    # 길이에 비례한다. 한글은 토큰당 글자 수가 영어보다 적어(토큰을 더 많이
    # 씀) 글자당 3토큰으로 넉넉하게 잡는다 - 수정 반영 과정에서 원본보다
    # 늘어나는 경우(설명 보강, 목록/표 추가 등)도 흔해서 원본 길이만 보고
    # 너무 빠듯하게 잡으면 실제로 자주 잘린다.
    computed = max(DEFAULT_MAX_OUTPUT_TOKENS, len(text) * 3 + 2048)

    max_output_tokens_raw = os.environ.get("LLM_MAX_OUTPUT_TOKENS")
    if not max_output_tokens_raw:
        return computed

    # LLM_MAX_OUTPUT_TOKENS를 지정했으면 "최소 이 정도는 보장"하는 하한으로
    # 다룬다 - 문서 길이 기반 추정치가 이보다 크면 그쪽을 쓴다. .env.example의
    # 예시 값(4096)을 그대로 켜뒀다가, 그보다 긴 문서에서 또 잘리는 걸 막기
    # 위함이다. 반대로 더 큰 값을 명시하면(모델이 감당 가능하다고 알고 있는
    # 경우) 그 값이 여전히 우선한다.
    return max(int(max_output_tokens_raw), computed)


def _generate_revised_document(
    page: ConfluencePage, text: str, suggestions: list[Suggestion], model: str, timeout: float
) -> tuple[str | None, str | None]:
    """문서 전체 수정본을 만들어본다 (best-effort).

    이 호출은 출력이 길어서(문서 전체를 거의 그대로 다시 써야 함) 소형
    모델일수록 중간에 잘리거나 실패하기 쉽고, max_tokens를 모델의 실제 최대
    컨텍스트 길이보다 크게 잡으면 서버가 요청 자체를 거부하기도 한다.
    new_findings/rule_fixes(더 짧고 안정적으로 성공하는 부분)와 분리된 별도
    호출로 두고, 실패해도 예외를 던지지 않는다 - 그래야 이 부분만 실패했을
    때도 호출자가 이미 성공한 결과를 잃지 않는다.

    (revised_document, 실패 사유) 튜플을 반환한다. 성공하면 실패 사유는 None,
    실패하면 revised_document가 None이고 실패 사유에 원인 문자열이 담긴다 -
    호출자가 이 사유를 리포트에 남겨서, "왜 수정본이 안 만들어졌는지"를 서버
    로그를 안 봐도 알 수 있게 한다.
    """
    max_output_tokens = _revision_max_output_tokens(text)
    user_content = _build_revision_user_content(page, text, suggestions)

    try:
        response = _client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": REVISION_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            timeout=timeout,
            max_tokens=max_output_tokens,
        )
    except Exception as e:  # noqa: BLE001 - best-effort, 실패해도 나머지 결과는 살림
        _logger.warning("수정본 생성 호출 실패 (max_tokens=%s): %s", max_output_tokens, e)
        return None, f"LLM 호출에 실패했습니다: {e}"

    choice = response.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        # 여기 걸렸다는 건 "우리가 요청한 max_tokens"에 먼저 도달해서 서버가
        # 응답을 끊었다는 뜻이다 - 모델의 실제 최대 컨텍스트 길이 자체를
        # 넘은 게 아니다(그랬다면 아래 except 절에서 요청 자체가 거부됐을
        # 것이다). 그래서 해결책은 반대로 LLM_MAX_OUTPUT_TOKENS를 "늘리는"
        # 것이다 - 모델이 감당 가능한 한도(서버의 --max-model-len 등) 안에서.
        error = (
            f"응답이 최대 토큰({max_output_tokens}) 제한으로 중간에 잘렸습니다. "
            ".env의 LLM_MAX_OUTPUT_TOKENS 값을 지금보다 늘려보세요(모델이 "
            "감당 가능한 최대 컨텍스트 길이 안에서). 값을 너무 크게 잡으면 "
            "이번처럼 잘리는 대신 요청 자체가 거부되는 다른 오류로 바뀌니, "
            "그 오류 메시지에 나오는 한도를 참고해서 다시 낮추면 됩니다."
        )
        _logger.warning("수정본 생성 응답 잘림 (max_tokens=%s)", max_output_tokens)
        return None, error

    revised = (choice.message.content or "").strip()
    if not revised:
        return None, "LLM이 빈 응답을 반환했습니다."
    return revised, None


def review_findings_with_llm(page: ConfluencePage, rule_suggestions: list[Suggestion] | None = None) -> list[Suggestion]:
    """찾기/수정안 채우기 LLM 호출만 수행한다 (최종 수정본 생성은 제외 -
    generate_revision() 참고). 웹 UI의 "AI 분석" 버튼이 이 함수만 쓴다 -
    최종 수정본 생성(가장 자주 실패하는 부분)과 분리해서, 이쪽만 먼저 빠르게
    끝내고 결과를 보여줄 수 있게 한다.

    rule_suggestions를 넘기면, 그 각각에 대해 LLM이 실제 문서 내용을 참고해
    만든 구체적인(복사-붙여넣기 가능한) 수정안으로 suggestion 필드를 갱신하고,
    거기에 LLM이 새로 찾은 문제들을 더해서 반환한다. rule_suggestions를 안
    넘기면 새로 찾은 문제들만 반환한다 (규칙 없이 LLM 검토만 쓰는 경우).

    LLM_BASE_URL이 없으면 rule_suggestions를 그대로(원래 조언 형태로)
    반환한다. 그 외 설정 누락이나 호출 자체의 실패는 최대
    FINDINGS_MAX_ATTEMPTS번 재시도해 본 뒤 LLMReviewError로 감싸서 던진다.
    """
    rule_suggestions = rule_suggestions or []

    if not is_llm_configured():
        return list(rule_suggestions)

    model = os.environ.get("LLM_MODEL")
    if not model:
        raise LLMReviewError("LLM_BASE_URL은 설정됐지만 LLM_MODEL이 설정되지 않았습니다.")

    max_chars_raw = os.environ.get("LLM_MAX_INPUT_CHARS")
    max_chars = int(max_chars_raw) if max_chars_raw else DEFAULT_MAX_INPUT_CHARS
    timeout_raw = os.environ.get("LLM_TIMEOUT_SECONDS")
    timeout = float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT_SECONDS

    text = storage_html_to_plain_text(page.storage_html, max_chars=max_chars)
    if not text.strip():
        return list(rule_suggestions)

    user_content = _build_user_content(page, text, rule_suggestions)
    max_output_tokens = _findings_max_output_tokens(rule_suggestions)

    data: dict | None = None
    last_error: LLMReviewError | None = None
    for _attempt in range(FINDINGS_MAX_ATTEMPTS):
        try:
            data = _run_findings_call(model, timeout, user_content, max_output_tokens)
            break
        except LLMReviewError as e:
            last_error = e
    if data is None:
        raise last_error

    updated_rule_suggestions = _apply_rule_fixes(rule_suggestions, data["rule_fixes"])
    new_findings = _to_suggestions(data["new_findings"])
    return updated_rule_suggestions + new_findings


def generate_revision(page: ConfluencePage, suggestions: list[Suggestion] | None = None) -> tuple[str | None, str | None]:
    """최종 수정본만 별도로 (재)생성한다. 웹 UI의 "최종 수정본 제안" 버튼이
    이 함수를 쓴다 - findings 호출과 독립적이라, 실패해도 findings 결과를
    다시 만들 필요 없이 이 호출만 다시 시도할 수 있다.

    (revised_document, 실패 사유) 튜플을 반환한다 - 성공하면 실패 사유는
    None, 실패하면(LLM 미설정 포함) revised_document가 None이고 실패
    사유에 원인 문자열이 담긴다. review_with_llm()과 달리 예외를 던지지
    않는다 - 항상 이 튜플로 결과를 알린다.
    """
    suggestions = suggestions or []

    if not is_llm_configured():
        return None, "LLM이 설정되어 있지 않습니다 (LLM_BASE_URL 미설정)."

    model = os.environ.get("LLM_MODEL")
    if not model:
        return None, "LLM_BASE_URL은 설정됐지만 LLM_MODEL이 설정되지 않았습니다."

    max_chars_raw = os.environ.get("LLM_MAX_INPUT_CHARS")
    max_chars = int(max_chars_raw) if max_chars_raw else DEFAULT_MAX_INPUT_CHARS
    timeout_raw = os.environ.get("LLM_TIMEOUT_SECONDS")
    timeout = float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT_SECONDS

    text = storage_html_to_plain_text(page.storage_html, max_chars=max_chars)
    if not text.strip():
        return None, "문서 내용이 비어 있습니다."

    return _generate_revised_document(page, text, suggestions, model, timeout)


def review_with_llm(page: ConfluencePage, rule_suggestions: list[Suggestion] | None = None) -> LLMReviewResult:
    """찾기/수정안(review_findings_with_llm)과 최종 수정본(generate_revision)을
    한 번에 모두 수행한다. CLI처럼 한 번의 호출로 전부 필요한 경우에 쓴다
    (웹 UI는 "AI 분석"과 "최종 수정본 제안"을 독립된 버튼으로 나눠서 각각
    review_findings_with_llm/generate_revision을 따로 호출한다).

    두 번째 호출(수정본 생성)은 출력이 길어 실패하기 쉬우므로 best-effort로
    처리한다 - 실패해도 예외를 던지지 않고 revised_document만 None으로 둔다
    (첫 번째 호출에서 이미 얻은 suggestions는 그대로 유지된다). 대신 실패
    사유를 `llm-revision-error` rule_id를 가진 info 등급 suggestion으로
    추가해서, 리포트에서 왜 수정본이 없는지 바로 확인할 수 있게 한다.

    LLM_BASE_URL이 없으면 rule_suggestions를 그대로(원래 조언 형태로) 담고
    revised_document는 None인 결과를 반환한다. 그 외 설정 누락이나 첫 번째
    호출(찾기/수정안) 자체의 실패는 review_findings_with_llm이 최대
    FINDINGS_MAX_ATTEMPTS번 재시도해 본 뒤 LLMReviewError로 던진다.
    """
    rule_suggestions = rule_suggestions or []

    if not is_llm_configured():
        return LLMReviewResult(suggestions=list(rule_suggestions), revised_document=None)

    # 문서 내용이 비어 있으면 findings/revision 둘 다 시도할 이유가 없다 -
    # review_findings_with_llm/generate_revision이 각자 이 경우를 조용히
    # 처리하지만(빈 문서를 계속 재시도할 이유가 없어서 에러로 취급하지
    # 않는다), 여기서 미리 걸러야 generate_revision이 "문서 내용이 비어
    # 있습니다"를 revision_error로 반환해 불필요한 llm-revision-error
    # suggestion이 붙는 걸 막을 수 있다.
    max_chars_raw = os.environ.get("LLM_MAX_INPUT_CHARS")
    max_chars = int(max_chars_raw) if max_chars_raw else DEFAULT_MAX_INPUT_CHARS
    if not storage_html_to_plain_text(page.storage_html, max_chars=max_chars).strip():
        return LLMReviewResult(suggestions=list(rule_suggestions), revised_document=None)

    all_suggestions = review_findings_with_llm(page, rule_suggestions)
    revised_document, revision_error = generate_revision(page, all_suggestions)
    if revision_error:
        all_suggestions = all_suggestions + [
            Suggestion(
                rule_id="llm-revision-error",
                severity=Severity.INFO,
                location="문서 전체",
                message="문서 전체 수정본을 만들지 못했습니다.",
                suggestion=revision_error,
            )
        ]

    return LLMReviewResult(suggestions=all_suggestions, revised_document=revised_document)
