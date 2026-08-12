"""Confluence 페이지 하나를 파싱하고 규칙을 적용해 제안을 만든다."""

from __future__ import annotations

from dataclasses import dataclass

from .confluence_client import ConfluencePage
from .guidelines import GuidelineComplianceReport, check_guideline_compliance
from .llm_review import (
    LLMReviewError,
    generate_verified_revision,
    is_llm_configured,
    review_findings_with_llm,
    review_with_llm,
    storage_html_to_plain_text,
)
from .parser import parse_storage_html
from .rules import DEFAULT_RULES, Rule, Severity, Suggestion


@dataclass
class PageReport:
    page: ConfluencePage
    suggestions: list[Suggestion]
    guideline_compliance: GuidelineComplianceReport
    original_document: str
    # LLM이 만든, 발견 사항/수정안을 반영해 다시 쓴 문서 전체. LLM 미설정/실패면 None
    # (원본은 항상 있지만, 수정본은 LLM 없이는 만들 수 없음).
    revised_document: str | None
    # 수정본이 가이드라인을 실제로 지키는지 재검증한 결과. 수정본 자체가
    # 없거나(revised_document가 None), 검증을 아예 안 거친 경로(CLI의
    # analyze_page() 등)에서는 None이다 - 리포트는 이 값이 있을 때만
    # "수정본 상태" 컬럼을 추가로 보여준다.
    revision_guideline_compliance: GuidelineComplianceReport | None = None


def _check_rules(page: ConfluencePage, rules: list[Rule] | None) -> list[Suggestion]:
    active_rules = rules if rules is not None else DEFAULT_RULES
    doc = parse_storage_html(page.title, page.storage_html)
    suggestions: list[Suggestion] = []
    for rule in active_rules:
        suggestions.extend(rule.check(doc))
    return suggestions


def analyze_page(page: ConfluencePage, rules: list[Rule] | None = None) -> PageReport:
    """규칙 검사 + LLM 찾기/수정안 + 최종 수정본까지 한 번에 모두 수행한다.

    CLI처럼 한 번의 호출로 전부 필요한 경우에 쓴다. 웹 UI는 "AI 분석"과
    "최종 수정본 제안" 버튼을 독립적으로 두기 위해 이 함수 대신
    analyze_page_findings()/generate_page_revision()을 따로 호출한다.

    여기서 만드는 수정본은 review_with_llm()의 best-effort 생성 결과라
    (호출 수를 늘리지 않으려고) 별도 검증/보정을 거치지 않는다 - 그래서
    반환하는 PageReport.revision_guideline_compliance는 항상 None이다.
    "수정본이 실제로 가이드라인을 지키는지" 검증된 상태를 보려면 웹 UI의
    "최종 수정본 제안" 버튼(generate_page_revision)을 쓴다.
    """
    llm_configured = is_llm_configured()

    # 웹 UI에서 원본 vs 수정본을 나란히 보여줄 때 쓴다. 사람이 읽는 화면용이라
    # LLM 프롬프트용 자르기(max_chars)는 적용하지 않고 전체를 담는다.
    original_document = storage_html_to_plain_text(page.storage_html, max_chars=None, attachments=page.attachments)
    rule_suggestions = _check_rules(page, rules)

    # LLM이 설정돼 있으면, 규칙이 찾은 문제들도 LLM에게 같이 넘겨서 각각에 대한
    # 구체적인(복사-붙여넣기 가능한) 수정안을 채우고 문서 전체 수정본도 만들게
    # 한다. 실패하면 규칙 기반 결과(조언 형태의 suggestion)는 그대로 살리고
    # 실패 사실만 추가한다.
    suggestions: list[Suggestion] = list(rule_suggestions)
    revised_document: str | None = None
    llm_succeeded = False
    if llm_configured:
        try:
            result = review_with_llm(page, rule_suggestions=rule_suggestions)
            suggestions = result.suggestions
            revised_document = result.revised_document
            llm_succeeded = True
        except LLMReviewError as e:
            suggestions.append(
                Suggestion(
                    rule_id="llm-review-error",
                    severity=Severity.INFO,
                    location="문서 전체",
                    message="LLM 심층 검토를 완료하지 못했습니다.",
                    suggestion=str(e),
                )
            )

    # LLM 호출이 실패했으면 LLM 전용 가이드라인은 검증되지 않은 것이므로,
    # "확인 불가"로 표시되도록 llm_configured=False와 동일하게 취급한다
    # (설정은 됐지만 이번 검토에서 실제로 확인되지는 않았다는 뜻).
    guideline_compliance = check_guideline_compliance(suggestions, llm_configured=llm_succeeded)

    return PageReport(
        page=page,
        suggestions=suggestions,
        guideline_compliance=guideline_compliance,
        original_document=original_document,
        revised_document=revised_document,
    )


def analyze_page_findings(page: ConfluencePage, rules: list[Rule] | None = None) -> PageReport:
    """규칙 검사 + LLM 찾기/수정안 채우기까지만 수행한다 (최종 수정본 생성은
    제외). 웹 UI의 "AI 분석" 버튼이 쓴다 - 가장 자주 실패하는 최종 수정본
    생성 호출과 분리해서, 이쪽 결과는 먼저 빠르게 보여줄 수 있게 한다.
    revised_document는 항상 None이다 (generate_page_revision()으로 별도
    생성).
    """
    llm_configured = is_llm_configured()
    original_document = storage_html_to_plain_text(page.storage_html, max_chars=None, attachments=page.attachments)
    rule_suggestions = _check_rules(page, rules)

    suggestions: list[Suggestion] = list(rule_suggestions)
    llm_succeeded = False
    if llm_configured:
        try:
            suggestions = review_findings_with_llm(page, rule_suggestions=rule_suggestions)
            llm_succeeded = True
        except LLMReviewError as e:
            suggestions.append(
                Suggestion(
                    rule_id="llm-review-error",
                    severity=Severity.INFO,
                    location="문서 전체",
                    message="LLM 심층 검토를 완료하지 못했습니다.",
                    suggestion=str(e),
                )
            )

    guideline_compliance = check_guideline_compliance(suggestions, llm_configured=llm_succeeded)

    return PageReport(
        page=page,
        suggestions=suggestions,
        guideline_compliance=guideline_compliance,
        original_document=original_document,
        revised_document=None,
    )


def generate_page_revision(
    page: ConfluencePage, suggestions: list[Suggestion] | None = None
) -> tuple[str | None, list[Suggestion], bool, str | None]:
    """최종 수정본만 별도로 (재)생성한다. 웹 UI의 "최종 수정본 제안" 버튼이
    쓴다 - AI 분석(analyze_page_findings)과 독립적으로 호출/재시도할 수
    있다.

    만들기만 하고 끝내지 않고, 만든 수정본이 실제로 가이드라인을 지키는지
    검증해서 부족하면 다시 고치기를 몇 차례 반복한다(generate_verified_revision
    참고) - 검증 없이 내놓은 수정본은 실제로는 가이드라인을 잘 안 지킬 수
    있어서 신뢰하기 어렵다.

    (revised_document, 끝까지 해결 못한 문제 목록, 검증 성공 여부, 실패
    사유) 튜플을 반환한다. 호출자는 검증 성공 여부와 남은 문제 목록으로
    수정본용 GuidelineComplianceReport를 직접 만들어 PageReport.
    revision_guideline_compliance에 채워 넣는다(예: web/app.py).
    """
    return generate_verified_revision(page, suggestions)
