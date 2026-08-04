from .base import Rule, Severity, Suggestion
from .starter import (
    AmbiguousLinkTextRule,
    HeadingHierarchySkipRule,
    LongParagraphRule,
    MissingAltTextRule,
    MissingH1Rule,
    MissingTableHeaderRule,
)

DEFAULT_RULES: list[Rule] = [
    HeadingHierarchySkipRule(),
    MissingH1Rule(),
    MissingTableHeaderRule(),
    MissingAltTextRule(),
    AmbiguousLinkTextRule(),
    LongParagraphRule(),
]

__all__ = [
    "Rule",
    "Severity",
    "Suggestion",
    "DEFAULT_RULES",
    "AmbiguousLinkTextRule",
    "HeadingHierarchySkipRule",
    "LongParagraphRule",
    "MissingAltTextRule",
    "MissingH1Rule",
    "MissingTableHeaderRule",
]
