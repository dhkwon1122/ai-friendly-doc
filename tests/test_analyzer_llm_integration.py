from ai_friendly_doc.analyzer import analyze_page
from ai_friendly_doc.confluence_client import ConfluencePage
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
        lambda page: [
            Suggestion(
                rule_id="llm-review",
                severity=Severity.INFO,
                location="문서 전체",
                message="테스트 메시지",
                suggestion="테스트 제안",
            )
        ],
    )
    report = analyze_page(make_page())
    llm_suggestions = [s for s in report.suggestions if s.rule_id == "llm-review"]
    assert len(llm_suggestions) == 1
    assert llm_suggestions[0].message == "테스트 메시지"


def test_analyze_page_adds_error_suggestion_when_llm_call_fails(monkeypatch):
    from ai_friendly_doc.llm_review import LLMReviewError

    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")

    def _raise(page):
        raise LLMReviewError("모델을 찾을 수 없습니다")

    monkeypatch.setattr("ai_friendly_doc.analyzer.review_with_llm", _raise)

    report = analyze_page(make_page())

    error_suggestions = [s for s in report.suggestions if s.rule_id == "llm-review-error"]
    assert len(error_suggestions) == 1
    assert "모델을 찾을 수 없습니다" in error_suggestions[0].suggestion
    # 규칙 기반 제안은 LLM 실패와 무관하게 그대로 살아있어야 함 (여기선 표/이미지가
    # 없는 짧은 문서라 규칙 위반이 없을 수도 있으니, "죽지 않고 끝까지 돌았다"는
    # 사실 자체(예외 없이 report가 반환됨)로 충분히 검증됨.
