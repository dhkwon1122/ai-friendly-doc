from ai_friendly_doc.analyzer import analyze_page
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
