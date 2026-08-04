"""Confluence 페이지 하나를 파싱하고 규칙을 적용해 제안을 만든다."""

from __future__ import annotations

from dataclasses import dataclass

from .confluence_client import ConfluencePage
from .guidelines import ScoreReport, score_document
from .llm_review import LLMReviewError, is_llm_configured, review_with_llm, storage_html_to_plain_text
from .parser import parse_storage_html
from .rules import DEFAULT_RULES, Rule, Severity, Suggestion


@dataclass
class PageReport:
    page: ConfluencePage
    suggestions: list[Suggestion]
    guideline_score: ScoreReport
    original_document: str
    # LLM이 만든, 발견 사항/수정안을 반영해 다시 쓴 문서 전체. LLM 미설정/실패면 None
    # (원본은 항상 있지만, 수정본은 LLM 없이는 만들 수 없음).
    revised_document: str | None


def analyze_page(page: ConfluencePage, rules: list[Rule] | None = None) -> PageReport:
    active_rules = rules if rules is not None else DEFAULT_RULES
    doc = parse_storage_html(page.title, page.storage_html)
    llm_configured = is_llm_configured()

    # 웹 UI에서 원본 vs 수정본을 나란히 보여줄 때 쓴다. 사람이 읽는 화면용이라
    # LLM 프롬프트용 자르기(max_chars)는 적용하지 않고 전체를 담는다.
    original_document = storage_html_to_plain_text(page.storage_html, max_chars=None)

    rule_suggestions: list[Suggestion] = []
    for rule in active_rules:
        rule_suggestions.extend(rule.check(doc))

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
    guideline_score = score_document(suggestions, llm_configured=llm_succeeded)

    return PageReport(
        page=page,
        suggestions=suggestions,
        guideline_score=guideline_score,
        original_document=original_document,
        revised_document=revised_document,
    )
