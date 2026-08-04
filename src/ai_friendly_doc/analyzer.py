"""Confluence 페이지 하나를 파싱하고 규칙을 적용해 제안을 만든다."""

from __future__ import annotations

from dataclasses import dataclass

from .confluence_client import ConfluencePage
from .guidelines import ScoreReport, score_document
from .llm_review import LLMReviewError, is_llm_configured, review_with_llm
from .parser import parse_storage_html
from .rules import DEFAULT_RULES, Rule, Severity, Suggestion


@dataclass
class PageReport:
    page: ConfluencePage
    suggestions: list[Suggestion]
    guideline_score: ScoreReport


def analyze_page(page: ConfluencePage, rules: list[Rule] | None = None) -> PageReport:
    active_rules = rules if rules is not None else DEFAULT_RULES
    doc = parse_storage_html(page.title, page.storage_html)
    llm_configured = is_llm_configured()

    suggestions: list[Suggestion] = []
    for rule in active_rules:
        suggestions.extend(rule.check(doc))

    llm_succeeded = False
    if llm_configured:
        try:
            suggestions.extend(review_with_llm(page))
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

    return PageReport(page=page, suggestions=suggestions, guideline_score=guideline_score)
