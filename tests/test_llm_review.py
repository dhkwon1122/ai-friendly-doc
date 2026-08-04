import pytest

from ai_friendly_doc.confluence_client import ConfluencePage
from ai_friendly_doc.llm_review import (
    LLMReviewError,
    LLMReviewResult,
    _apply_rule_fixes,
    _build_user_content,
    _parse_llm_response,
    _to_suggestions,
    is_llm_configured,
    review_with_llm,
    storage_html_to_plain_text,
)
from ai_friendly_doc.rules import Severity, Suggestion


def make_page(storage_html: str = "<p>본문</p>") -> ConfluencePage:
    return ConfluencePage(
        id="1", title="테스트 문서", space_key="ENG", version=1, storage_html=storage_html, web_url=""
    )


def make_rule_suggestion(rule_id="missing-alt-text", location="이미지 #1", suggestion="alt 텍스트를 추가하세요.") -> Suggestion:
    return Suggestion(
        rule_id=rule_id,
        severity=Severity.WARNING,
        location=location,
        message="대체 텍스트가 없음",
        suggestion=suggestion,
        guideline_id="core-2",
    )


# ---- storage_html_to_plain_text ----------------------------------------


def test_plain_text_includes_heading_with_markdown_prefix():
    text = storage_html_to_plain_text("<h2>설치 방법</h2>")
    assert "## 설치 방법" in text


def test_plain_text_includes_paragraph_text():
    text = storage_html_to_plain_text("<p>이 문서는 배포 절차를 설명합니다.</p>")
    assert "이 문서는 배포 절차를 설명합니다." in text


def test_plain_text_includes_list_items():
    text = storage_html_to_plain_text("<ul><li>첫 번째</li><li>두 번째</li></ul>")
    assert "- 첫 번째" in text
    assert "- 두 번째" in text


def test_plain_text_includes_table_rows():
    html = "<table><tbody><tr><th>이름</th><th>값</th></tr><tr><td>a</td><td>1</td></tr></tbody></table>"
    text = storage_html_to_plain_text(html)
    assert "| 이름 | 값 |" in text
    assert "| a | 1 |" in text


def test_plain_text_shows_filename_when_alt_missing():
    text = storage_html_to_plain_text('<ac:image><ri:attachment ri:filename="deploy-diagram.png" /></ac:image>')
    assert "대체 텍스트 없음" in text
    assert "deploy-diagram.png" in text


def test_plain_text_uses_alt_when_present():
    text = storage_html_to_plain_text('<ac:image ac:alt="다이어그램"><ri:attachment /></ac:image>')
    assert "다이어그램" in text


def test_plain_text_truncates_when_too_long():
    html = "<p>" + ("가" * 100) + "</p>"
    text = storage_html_to_plain_text(html, max_chars=20)
    assert len(text) <= 20 + len("\n\n...(문서가 길어 이하 생략됨)")
    assert "생략됨" in text


# ---- _parse_llm_response ---------------------------------------------------


def test_parse_llm_response_plain_object():
    data = _parse_llm_response('{"new_findings": [{"severity": "info"}], "rule_fixes": []}')
    assert data["new_findings"] == [{"severity": "info"}]
    assert data["rule_fixes"] == []


def test_parse_llm_response_code_fenced():
    raw = '```json\n{"new_findings": [], "rule_fixes": [{"index": 0, "fix": "x"}]}\n```'
    data = _parse_llm_response(raw)
    assert data["rule_fixes"] == [{"index": 0, "fix": "x"}]


def test_parse_llm_response_extracts_object_from_surrounding_prose():
    raw = '결과입니다:\n{"new_findings": [], "rule_fixes": []}\n감사합니다.'
    data = _parse_llm_response(raw)
    assert data == {"new_findings": [], "rule_fixes": [], "revised_document": None}


def test_parse_llm_response_defaults_missing_keys_to_empty_lists():
    data = _parse_llm_response("{}")
    assert data == {"new_findings": [], "rule_fixes": [], "revised_document": None}


def test_parse_llm_response_extracts_revised_document():
    data = _parse_llm_response('{"new_findings": [], "rule_fixes": [], "revised_document": "# 수정본"}')
    assert data["revised_document"] == "# 수정본"


def test_parse_llm_response_raises_when_revised_document_not_a_string():
    with pytest.raises(LLMReviewError):
        _parse_llm_response('{"new_findings": [], "rule_fixes": [], "revised_document": 123}')


def test_parse_llm_response_raises_on_garbage():
    with pytest.raises(LLMReviewError):
        _parse_llm_response("이건 JSON이 아닙니다")


def test_parse_llm_response_raises_when_not_an_object():
    with pytest.raises(LLMReviewError):
        _parse_llm_response("[1, 2, 3]")


def test_parse_llm_response_raises_when_keys_not_lists():
    with pytest.raises(LLMReviewError):
        _parse_llm_response('{"new_findings": "oops", "rule_fixes": []}')


# ---- _to_suggestions -------------------------------------------------------


def test_to_suggestions_maps_fields():
    items = [{"severity": "critical", "location": "1절", "message": "모호함", "suggestion": "명시할 것"}]
    suggestions = _to_suggestions(items)
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.rule_id == "llm-review"
    assert s.severity == Severity.CRITICAL
    assert s.location == "1절"
    assert s.message == "모호함"
    assert s.suggestion == "명시할 것"


def test_to_suggestions_defaults_invalid_severity_to_info():
    suggestions = _to_suggestions([{"severity": "urgent!!"}])
    assert suggestions[0].severity == Severity.INFO


def test_to_suggestions_skips_non_dict_items():
    assert _to_suggestions(["오류", 123]) == []


def test_to_suggestions_keeps_valid_guideline_id():
    suggestions = _to_suggestions([{"severity": "warning", "guideline": "core-1"}])
    assert suggestions[0].guideline_id == "core-1"


def test_to_suggestions_drops_unknown_guideline_id():
    suggestions = _to_suggestions([{"severity": "warning", "guideline": "other"}])
    assert suggestions[0].guideline_id is None


# ---- _apply_rule_fixes ------------------------------------------------------


def test_apply_rule_fixes_replaces_matched_suggestion():
    rule_suggestions = [make_rule_suggestion()]
    fixes = [{"index": 0, "fix": "alt=\"배포 아키텍처 다이어그램\""}]
    updated = _apply_rule_fixes(rule_suggestions, fixes)
    assert updated[0].suggestion == 'alt="배포 아키텍처 다이어그램"'
    # 나머지 필드는 그대로 유지되어야 함
    assert updated[0].rule_id == "missing-alt-text"
    assert updated[0].guideline_id == "core-2"


def test_apply_rule_fixes_keeps_original_when_no_matching_fix():
    rule_suggestions = [make_rule_suggestion(suggestion="원래 조언")]
    updated = _apply_rule_fixes(rule_suggestions, fixes=[])
    assert updated[0].suggestion == "원래 조언"


def test_apply_rule_fixes_ignores_out_of_range_index():
    rule_suggestions = [make_rule_suggestion(suggestion="원래 조언")]
    updated = _apply_rule_fixes(rule_suggestions, fixes=[{"index": 5, "fix": "무관한 수정"}])
    assert updated[0].suggestion == "원래 조언"


def test_apply_rule_fixes_ignores_blank_fix_text():
    rule_suggestions = [make_rule_suggestion(suggestion="원래 조언")]
    updated = _apply_rule_fixes(rule_suggestions, fixes=[{"index": 0, "fix": "   "}])
    assert updated[0].suggestion == "원래 조언"


def test_apply_rule_fixes_handles_multiple_items_independently():
    rule_suggestions = [
        make_rule_suggestion(location="이미지 #1", suggestion="원래1"),
        make_rule_suggestion(location="이미지 #2", suggestion="원래2"),
    ]
    fixes = [{"index": 1, "fix": "수정됨"}]
    updated = _apply_rule_fixes(rule_suggestions, fixes)
    assert updated[0].suggestion == "원래1"
    assert updated[1].suggestion == "수정됨"


# ---- _build_user_content ----------------------------------------------------


def test_build_user_content_includes_numbered_rule_findings():
    page = make_page()
    content = _build_user_content(page, "본문 텍스트", [make_rule_suggestion(location="이미지 #1")])
    assert "0. [missing-alt-text] 이미지 #1: 대체 텍스트가 없음" in content
    assert "본문 텍스트" in content


def test_build_user_content_omits_findings_section_when_empty():
    page = make_page()
    content = _build_user_content(page, "본문 텍스트", [])
    assert "구조 검사로 발견된" not in content


# ---- review_with_llm (네트워크 호출은 모두 모킹) ----------------------------


def test_review_with_llm_returns_rule_suggestions_unchanged_when_not_configured(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert is_llm_configured() is False
    rule_suggestions = [make_rule_suggestion(suggestion="원래 조언")]
    result = review_with_llm(make_page(), rule_suggestions=rule_suggestions)
    assert result == LLMReviewResult(suggestions=rule_suggestions, revised_document=None)


def test_review_with_llm_returns_empty_when_not_configured_and_no_rules(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    result = review_with_llm(make_page())
    assert result.suggestions == []
    assert result.revised_document is None


def test_review_with_llm_raises_when_model_missing(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(LLMReviewError):
        review_with_llm(make_page())


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content, finish_reason="stop"):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, content, finish_reason="stop"):
        self.choices = [_FakeChoice(content, finish_reason=finish_reason)]


class _FakeCompletions:
    def __init__(self, content=None, exc=None, finish_reason="stop"):
        self._content = content
        self._exc = exc
        self._finish_reason = finish_reason
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self._exc:
            raise self._exc
        return _FakeResponse(self._content, finish_reason=self._finish_reason)


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, content=None, exc=None, finish_reason="stop"):
        self.chat = _FakeChat(_FakeCompletions(content=content, exc=exc, finish_reason=finish_reason))


def test_review_with_llm_fills_in_rule_fix_and_adds_new_finding(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    fake_client = _FakeClient(
        content=(
            '{"new_findings": [{"severity": "warning", "message": "모호한 표현", '
            '"suggestion": "이것 -> 배포 스크립트", "guideline": "core-1"}], '
            '"rule_fixes": [{"index": 0, "fix": "alt=\\"배포 아키텍처 다이어그램\\""}], '
            '"revised_document": "# 수정본 전체"}'
        )
    )
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    rule_suggestions = [make_rule_suggestion(suggestion="alt 텍스트를 추가하세요.")]
    result = review_with_llm(make_page("<p>이거 해두세요.</p>"), rule_suggestions=rule_suggestions)

    assert len(result.suggestions) == 2
    fixed_rule_suggestion = next(s for s in result.suggestions if s.rule_id == "missing-alt-text")
    assert fixed_rule_suggestion.suggestion == 'alt="배포 아키텍처 다이어그램"'
    new_finding = next(s for s in result.suggestions if s.rule_id == "llm-review")
    assert new_finding.guideline_id == "core-1"
    assert result.revised_document == "# 수정본 전체"
    assert fake_client.chat.completions.last_kwargs["model"] == "qwen2.5-32b-instruct"


def test_review_with_llm_call_failure_wraps_as_llmreviewerror(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    fake_client = _FakeClient(exc=ConnectionError("연결 실패"))
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    with pytest.raises(LLMReviewError):
        review_with_llm(make_page())


def test_review_with_llm_skips_empty_document(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    fake_client = _FakeClient(content='{"new_findings": [], "rule_fixes": []}')
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    rule_suggestions = [make_rule_suggestion(suggestion="원래 조언")]
    result = review_with_llm(make_page(""), rule_suggestions=rule_suggestions)
    assert result == LLMReviewResult(suggestions=rule_suggestions, revised_document=None)
    assert fake_client.chat.completions.last_kwargs is None


def test_review_with_llm_scales_max_tokens_with_document_length(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    monkeypatch.delenv("LLM_MAX_OUTPUT_TOKENS", raising=False)
    fake_client = _FakeClient(content='{"new_findings": [], "rule_fixes": [], "revised_document": "x"}')
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    long_html = "<p>" + ("가나다라마바사아자차카타파하 " * 500) + "</p>"
    review_with_llm(make_page(long_html))

    used_max_tokens = fake_client.chat.completions.last_kwargs["max_tokens"]
    assert used_max_tokens > 4096  # 문서가 길면 기본값보다 커야 함


def test_review_with_llm_respects_explicit_max_output_tokens_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "777")
    fake_client = _FakeClient(content='{"new_findings": [], "rule_fixes": [], "revised_document": "x"}')
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    review_with_llm(make_page())

    assert fake_client.chat.completions.last_kwargs["max_tokens"] == 777


def test_review_with_llm_raises_clear_error_when_response_truncated(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    fake_client = _FakeClient(content='{"new_findings": [], "rule_fixes"', finish_reason="length")
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    with pytest.raises(LLMReviewError, match="잘렸습니다"):
        review_with_llm(make_page())


def test_system_prompt_excludes_html_only_visible_guidelines():
    from ai_friendly_doc.llm_review import SYSTEM_PROMPT

    # 원본 HTML(colspan/매크로/스타일 태그)에만 있는 정보라 평문 프롬프트로는
    # LLM이 판단할 수 없는 가이드라인은 체크리스트에서 빠져 있어야 한다.
    assert "extra-2" not in SYSTEM_PROMPT
    assert "extra-3" not in SYSTEM_PROMPT
    assert "extra-7" not in SYSTEM_PROMPT
    # 핵심 가이드라인 7개는 전부 LLM이 판단 가능하므로 프롬프트에 포함돼야 한다.
    for i in range(1, 8):
        assert f"core-{i}" in SYSTEM_PROMPT
