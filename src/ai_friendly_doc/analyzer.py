"""Confluence 페이지 하나를 파싱하고 규칙을 적용해 제안을 만든다."""

from __future__ import annotations

from dataclasses import dataclass

from .confluence_client import ConfluencePage
from .llm_review import LLMReviewError, is_llm_configured, review_with_llm
from .parser import parse_storage_html
from .rules import DEFAULT_RULES, Rule, Severity, Suggestion


@dataclass
class PageReport:
    page: ConfluencePage
    suggestions: list[Suggestion]


def analyze_page(page: ConfluencePage, rules: list[Rule] | None = None) -> PageReport:
    active_rules = rules if rules is not None else DEFAULT_RULES
    doc = parse_storage_html(page.title, page.storage_html)

    suggestions: list[Suggestion] = []
    for rule in active_rules:
        suggestions.extend(rule.check(doc))

    if is_llm_configured():
        try:
            suggestions.extend(review_with_llm(page))
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

    return PageReport(page=page, suggestions=suggestions)
