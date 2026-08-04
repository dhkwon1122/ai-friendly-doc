"""Confluence 페이지 하나를 파싱하고 규칙을 적용해 제안을 만든다."""

from __future__ import annotations

from dataclasses import dataclass

from .confluence_client import ConfluencePage
from .parser import parse_storage_html
from .rules import DEFAULT_RULES, Rule, Suggestion


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

    return PageReport(page=page, suggestions=suggestions)
