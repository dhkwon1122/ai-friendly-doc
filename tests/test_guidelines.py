from ai_friendly_doc.guidelines import CORE_GUIDELINES, GUIDELINES, check_guideline_compliance
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


def test_all_compliant_when_no_violations_and_llm_configured():
    report = check_guideline_compliance([], llm_configured=True)
    assert all(r.status == "compliant" for r in report.results)


def test_llm_only_guidelines_are_unverifiable_when_llm_not_configured():
    report = check_guideline_compliance([], llm_configured=False)
    llm_only_ids = {g.id for g in CORE_GUIDELINES if g.llm_only}
    non_llm_only_ids = {g.id for g in CORE_GUIDELINES if not g.llm_only}

    unverifiable_ids = {r.guideline.id for r in report.results if r.status == "unverifiable"}
    compliant_ids = {r.guideline.id for r in report.results if r.status == "compliant"}

    assert unverifiable_ids == llm_only_ids
    assert compliant_ids == non_llm_only_ids


def test_violation_marks_guideline_as_violated_even_without_llm():
    suggestions = [make_suggestion("core-6")]
    report = check_guideline_compliance(suggestions, llm_configured=False)
    result = next(r for r in report.results if r.guideline.id == "core-6")
    assert result.status == "violated"
    assert result.violation_count == 1


def test_suggestions_without_core_guideline_id_do_not_affect_other_results():
    # None(가이드라인 미지정)이나 extra-2(core가 아님)는 core 결과에
    # 영향을 주면 안 된다.
    suggestions = [make_suggestion(None), make_suggestion("extra-2")]
    report = check_guideline_compliance(suggestions, llm_configured=True)
    assert all(r.status == "compliant" for r in report.results)


def test_multiple_violations_on_same_guideline_count_correctly():
    suggestions = [make_suggestion("core-6"), make_suggestion("core-6"), make_suggestion("core-6")]
    report = check_guideline_compliance(suggestions, llm_configured=True)
    result = next(r for r in report.results if r.guideline.id == "core-6")
    assert result.violation_count == 3
    assert result.status == "violated"


# ---- rule_engine_ran=False (최종 수정본처럼 규칙 엔진이 안 도는 경우) -----


def test_rule_engine_ran_false_marks_all_unverifiable_when_llm_not_configured():
    # 수정본은 평문이라 규칙 엔진이 아예 못 돈다 - llm_only가 아닌
    # 가이드라인도 검증(LLM 재검토) 없이는 준수 여부를 알 수 없으므로,
    # rule_engine_ran=False면 llm_only 여부와 무관하게 전부 "확인 불가"여야
    # 한다(rule_engine_ran=True인 원본 채점과 다른 점).
    report = check_guideline_compliance([], llm_configured=False, rule_engine_ran=False)
    assert all(r.status == "unverifiable" for r in report.results)


def test_rule_engine_ran_false_marks_compliant_when_llm_configured_and_no_violations():
    report = check_guideline_compliance([], llm_configured=True, rule_engine_ran=False)
    assert all(r.status == "compliant" for r in report.results)


def test_rule_engine_ran_false_still_marks_violations():
    suggestions = [make_suggestion("core-2")]
    report = check_guideline_compliance(suggestions, llm_configured=True, rule_engine_ran=False)
    result = next(r for r in report.results if r.guideline.id == "core-2")
    assert result.status == "violated"
