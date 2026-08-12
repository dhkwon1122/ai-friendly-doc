from ai_friendly_doc.analyzer import analyze_page, analyze_page_findings, generate_page_revision
from ai_friendly_doc.confluence_client import ConfluencePage
from ai_friendly_doc.llm_review import LLMReviewResult
from ai_friendly_doc.rules import Severity, Suggestion


def make_page(storage_html: str = "<h1>제목</h1><p>본문</p>") -> ConfluencePage:
    return ConfluencePage(
        id="1", title="테스트 문서", space_key="ENG", version=1, storage_html=storage_html, web_url=""
    )


def test_analyze_page_skips_llm_when_not_configured(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    report = analyze_page(make_page())
    assert all(s.rule_id not in ("llm-review", "llm-review-error") for s in report.suggestions)


def test_analyze_page_includes_llm_suggestions_when_configured(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setattr(
        "ai_friendly_doc.analyzer.review_with_llm",
        lambda page, rule_suggestions=None: LLMReviewResult(
            suggestions=list(rule_suggestions or [])
            + [
                Suggestion(
                    rule_id="llm-review",
                    severity=Severity.INFO,
                    location="문서 전체",
                    message="테스트 메시지",
                    suggestion="테스트 제안",
                )
            ],
            revised_document="# 수정본",
        ),
    )
    report = analyze_page(make_page())
    llm_suggestions = [s for s in report.suggestions if s.rule_id == "llm-review"]
    assert len(llm_suggestions) == 1
    assert llm_suggestions[0].message == "테스트 메시지"
    assert report.revised_document == "# 수정본"


def test_analyze_page_sets_original_document():
    report = analyze_page(make_page("<h1>제목</h1><p>본문 내용</p>"))
    assert "본문 내용" in report.original_document


def test_analyze_page_revised_document_none_when_llm_not_configured(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    report = analyze_page(make_page())
    assert report.revised_document is None


def test_analyze_page_adds_error_suggestion_when_llm_call_fails(monkeypatch):
    from ai_friendly_doc.llm_review import LLMReviewError

    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")

    def _raise(page, rule_suggestions=None):
        raise LLMReviewError("모델을 찾을 수 없습니다")

    monkeypatch.setattr("ai_friendly_doc.analyzer.review_with_llm", _raise)

    # H1이 없는 문서라 missing-h1 규칙 위반이 하나 잡히는 페이지로 테스트해서,
    # LLM 호출이 실패해도 규칙 기반 제안이 안 사라지는지 직접 확인한다.
    report = analyze_page(make_page("<h2>제목</h2><p>본문</p>"))

    error_suggestions = [s for s in report.suggestions if s.rule_id == "llm-review-error"]
    assert len(error_suggestions) == 1
    assert "모델을 찾을 수 없습니다" in error_suggestions[0].suggestion

    rule_based = [s for s in report.suggestions if s.rule_id == "missing-h1"]
    assert len(rule_based) == 1


# ---- analyze_page_findings / generate_page_revision (독립 호출, "AI 분석" /
# "최종 수정본 제안" 버튼용) --------------------------------------------------


def test_analyze_page_findings_never_generates_revised_document(monkeypatch):
    # "AI 분석" 버튼은 findings만 하고 수정본 생성 호출 자체를 하지 않아야
    # 한다 - review_with_llm이 아니라 review_findings_with_llm을 호출하는지
    # 확인한다(review_with_llm을 실수로 부르면 여기서 걸린다).
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")

    def _fail_if_called(*a, **k):
        raise AssertionError("analyze_page_findings가 review_with_llm(수정본 생성 포함)을 호출하면 안 된다")

    monkeypatch.setattr("ai_friendly_doc.analyzer.review_with_llm", _fail_if_called)
    monkeypatch.setattr(
        "ai_friendly_doc.analyzer.review_findings_with_llm",
        lambda page, rule_suggestions=None: list(rule_suggestions or []),
    )

    report = analyze_page_findings(make_page())
    assert report.revised_document is None


def test_analyze_page_findings_includes_llm_suggestions_when_configured(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setattr(
        "ai_friendly_doc.analyzer.review_findings_with_llm",
        lambda page, rule_suggestions=None: list(rule_suggestions or [])
        + [
            Suggestion(
                rule_id="llm-review",
                severity=Severity.INFO,
                location="문서 전체",
                message="테스트 메시지",
                suggestion="테스트 제안",
            )
        ],
    )
    report = analyze_page_findings(make_page())
    llm_suggestions = [s for s in report.suggestions if s.rule_id == "llm-review"]
    assert len(llm_suggestions) == 1
    assert report.revised_document is None


def test_analyze_page_findings_adds_error_suggestion_when_llm_call_fails(monkeypatch):
    from ai_friendly_doc.llm_review import LLMReviewError

    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")

    def _raise(page, rule_suggestions=None):
        raise LLMReviewError("모델을 찾을 수 없습니다")

    monkeypatch.setattr("ai_friendly_doc.analyzer.review_findings_with_llm", _raise)

    report = analyze_page_findings(make_page("<h2>제목</h2><p>본문</p>"))
    error_suggestions = [s for s in report.suggestions if s.rule_id == "llm-review-error"]
    assert len(error_suggestions) == 1
    rule_based = [s for s in report.suggestions if s.rule_id == "missing-h1"]
    assert len(rule_based) == 1


def test_generate_page_revision_delegates_to_llm_review(monkeypatch):
    monkeypatch.setattr(
        "ai_friendly_doc.analyzer.generate_verified_revision",
        lambda page, suggestions=None: ("# 최종 수정본", [], True, None),
    )
    revised, unresolved, verified, error = generate_page_revision(make_page(), [])
    assert revised == "# 최종 수정본"
    assert unresolved == []
    assert verified is True
    assert error is None


def test_generate_page_revision_can_be_called_without_prior_findings(monkeypatch):
    # AI 분석을 먼저 안 돌려도(suggestions가 None/빈 리스트여도) 동작해야
    # 한다 - "최종 수정본 제안" 버튼을 처음부터 바로 눌러도 되게 하려는 목적.
    captured = {}

    def _fake_generate_verified_revision(page, suggestions=None):
        captured["suggestions"] = suggestions
        return "# 수정본", [], True, None

    monkeypatch.setattr("ai_friendly_doc.analyzer.generate_verified_revision", _fake_generate_verified_revision)
    revised, unresolved, verified, error = generate_page_revision(make_page(), None)
    assert revised == "# 수정본"
    assert unresolved == []
    assert captured["suggestions"] is None
