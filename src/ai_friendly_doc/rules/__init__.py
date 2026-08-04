from .base import Rule, Severity, Suggestion
from .starter import (
    AmbiguousLinkTextRule,
    ExcessiveMacroRule,
    HeadingHierarchySkipRule,
    LongParagraphRule,
    MergedOrNestedTableRule,
    MissingAltTextRule,
    MissingH1Rule,
    MissingTableHeaderRule,
    PseudoNumberedListRule,
    RelativeTimeExpressionRule,
    VagueHeadingRule,
)

DEFAULT_RULES: list[Rule] = [
    HeadingHierarchySkipRule(),
    MissingH1Rule(),
    MissingTableHeaderRule(),
    MissingAltTextRule(),
    AmbiguousLinkTextRule(),
    LongParagraphRule(),
    RelativeTimeExpressionRule(),
    MergedOrNestedTableRule(),
    VagueHeadingRule(),
    PseudoNumberedListRule(),
    ExcessiveMacroRule(),
]

__all__ = [
    "Rule",
    "Severity",
    "Suggestion",
    "DEFAULT_RULES",
    "AmbiguousLinkTextRule",
    "ExcessiveMacroRule",
    "HeadingHierarchySkipRule",
    "LongParagraphRule",
    "MergedOrNestedTableRule",
    "MissingAltTextRule",
    "MissingH1Rule",
    "MissingTableHeaderRule",
    "PseudoNumberedListRule",
    "RelativeTimeExpressionRule",
    "VagueHeadingRule",
]
