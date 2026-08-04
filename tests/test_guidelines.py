from ai_friendly_doc.guidelines import CORE_GUIDELINES, GUIDELINES, score_document
from ai_friendly_doc.rules import Severity, Suggestion


def make_suggestion(guideline_id: str | None) -> Suggestion:
    return Suggestion(
        rule_id="test-rule",
        severity=Severity.WARNING,
        location="문서 전체",
        message="문제",
        suggestion="제안",
        guideline_id=guideline_id,
    )


def test_fourteen_guidelines_seven_core_seven_extra():
    assert len(GUIDELINES) == 14
    assert len(CORE_GUIDELINES) == 7
    assert len([g for g in GUIDELINES if g.tier == "extra"]) == 7


def test_score_is_100_when_no_violations_and_llm_configured():
    report = score_document([], llm_configured=True)
    assert report.score == 100
    assert report.checked_count == 7
    assert report.compliant_count == 7
    assert all(r.status == "compliant" for r in report.results)


def test_score_excludes_llm_only_guidelines_when_llm_not_configured():
    report = score_document([], llm_configured=False)
    llm_only_ids = {g.id for g in CORE_GUIDELINES if g.llm_only}
    non_llm_only_ids = {g.id for g in CORE_GUIDELINES if not g.llm_only}

    unverifiable_ids = {r.guideline.id for r in report.results if r.status == "unverifiable"}
    compliant_ids = {r.guideline.id for r in report.results if r.status == "compliant"}

    assert unverifiable_ids == llm_only_ids
    assert compliant_ids == non_llm_only_ids
    assert report.checked_count == len(non_llm_only_ids)
    assert report.score == 100  # 확인 가능한 항목 중에는 위반이 없음


def test_violation_marks_guideline_as_violated_even_without_llm():
    suggestions = [make_suggestion("core-6")]
    report = score_document(suggestions, llm_configured=False)
    result = next(r for r in report.results if r.guideline.id == "core-6")
    assert result.status == "violated"
    assert result.violation_count == 1


def test_score_reflects_ratio_of_violated_to_checked():
    # llm_configured=True -> 7개 전부 확인 대상. 그 중 2개 위반.
    suggestions = [make_suggestion("core-1"), make_suggestion("core-6")]
    report = score_document(suggestions, llm_configured=True)
    assert report.checked_count == 7
    assert report.compliant_count == 5
    assert report.score == round(100 * 5 / 7)


def test_suggestions_without_guideline_id_do_not_affect_score():
    suggestions = [make_suggestion(None), make_suggestion("extra-2")]  # extra-2는 core가 아니라 점수 무관
    report = score_document(suggestions, llm_configured=True)
    assert report.score == 100


def test_multiple_violations_on_same_guideline_count_correctly():
    suggestions = [make_suggestion("core-6"), make_suggestion("core-6"), make_suggestion("core-6")]
    report = score_document(suggestions, llm_configured=True)
    result = next(r for r in report.results if r.guideline.id == "core-6")
    assert result.violation_count == 3
    assert result.status == "violated"
