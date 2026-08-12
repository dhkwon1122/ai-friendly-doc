import pytest

from ai_friendly_doc.confluence_client import Attachment, ConfluencePage
from ai_friendly_doc.llm_review import (
    LLMReviewError,
    LLMReviewResult,
    _apply_rule_fixes,
    _build_revision_user_content,
    _build_user_content,
    _parse_llm_response,
    _to_suggestions,
    generate_revision,
    is_llm_configured,
    review_findings_with_llm,
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


def test_plain_text_numbers_ordered_list_items_sequentially():
    # ol을 ul과 똑같이 "- "로 바꿔버리면 원본이 순서 있는(번호 매겨진)
    # 목록이었다는 사실 자체가 LLM에게 안 보인다 - 실제 1, 2, 3 번호를
    # 매겨서 순서 목록이었다는 사실과 항목 순서를 함께 전달해야 한다.
    text = storage_html_to_plain_text("<ol><li>첫 단계</li><li>두 번째 단계</li><li>세 번째 단계</li></ol>")
    assert "1. 첫 단계" in text
    assert "2. 두 번째 단계" in text
    assert "3. 세 번째 단계" in text


def test_plain_text_includes_table_rows():
    html = "<table><tbody><tr><th>이름</th><th>값</th></tr><tr><td>a</td><td>1</td></tr></tbody></table>"
    text = storage_html_to_plain_text(html)
    assert "| 이름 | 값 |" in text
    assert "| a | 1 |" in text


def test_plain_text_includes_table_separator_row_after_header():
    # 마크다운 표는 헤더 바로 다음 줄에 "|---|---|" 구분선이 없으면 표로
    # 인식되지 않고 그냥 파이프가 섞인 텍스트로 취급된다(대부분의 마크다운
    # 파서가 GFM 표 문법을 따름) - 그러면 줄 사이 개행도 소프트 브레이크로
    # 접혀서 표 전체가 한 줄로 뭉개져 보인다.
    html = "<table><tbody><tr><th>이름</th><th>나이</th><th>직급</th></tr><tr><td>a</td><td>1</td><td>b</td></tr></tbody></table>"
    text = storage_html_to_plain_text(html)
    lines = text.splitlines()
    header_idx = lines.index("| 이름 | 나이 | 직급 |")
    assert lines[header_idx + 1] == "|---|---|---|"


def test_plain_text_shows_filename_when_alt_missing():
    text = storage_html_to_plain_text('<ac:image><ri:attachment ri:filename="deploy-diagram.png" /></ac:image>')
    assert "대체 텍스트 없음" in text
    assert "deploy-diagram.png" in text


def test_plain_text_uses_alt_when_present():
    text = storage_html_to_plain_text('<ac:image ac:alt="다이어그램"><ri:attachment /></ac:image>')
    assert "다이어그램" in text


def test_plain_text_adds_download_link_when_image_matches_attachment():
    # 이 도구는 Confluence에 쓰기 권한이 없어서 이미지 자체를 새 페이지로
    # 옮겨줄 수 없다 - 대신 실제 첨부파일 목록에서 파일명이 일치하면 사람이
    # 클릭해서 직접 받을 수 있는 다운로드 링크를 이미지 자리에 붙여준다.
    html = '<ac:image ac:alt="다이어그램"><ri:attachment ri:filename="diagram.png" /></ac:image>'
    attachments = [Attachment(filename="diagram.png", download_url="https://confluence.samsungds.net/download/attachments/1/diagram.png")]
    text = storage_html_to_plain_text(html, attachments=attachments)
    assert "[diagram.png](https://confluence.samsungds.net/download/attachments/1/diagram.png)" in text


def test_plain_text_omits_download_link_when_no_matching_attachment():
    html = '<ac:image ac:alt="다이어그램"><ri:attachment ri:filename="diagram.png" /></ac:image>'
    attachments = [Attachment(filename="다른파일.png", download_url="https://example.com/other.png")]
    text = storage_html_to_plain_text(html, attachments=attachments)
    assert "다운로드" not in text


def test_plain_text_omits_download_link_when_no_attachments_given():
    text = storage_html_to_plain_text('<ac:image ac:alt="다이어그램"><ri:attachment ri:filename="diagram.png" /></ac:image>')
    assert "다운로드" not in text


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
    assert data == {"new_findings": [], "rule_fixes": []}


def test_parse_llm_response_defaults_missing_keys_to_empty_lists():
    data = _parse_llm_response("{}")
    assert data == {"new_findings": [], "rule_fixes": []}


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


# ---- _build_revision_user_content -------------------------------------------


def test_build_revision_user_content_includes_document_and_suggestions():
    page = make_page()
    content = _build_revision_user_content(page, "본문 텍스트", [make_rule_suggestion(location="이미지 #1")])
    assert "본문 텍스트" in content
    assert "이미지 #1: 대체 텍스트가 없음 -> alt 텍스트를 추가하세요." in content


def test_build_revision_user_content_omits_suggestions_section_when_empty():
    page = make_page()
    content = _build_revision_user_content(page, "본문 텍스트", [])
    assert "반영해야 할 문제" not in content


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
    """responses는 (content, finish_reason) 튜플의 리스트로, 호출될 때마다 순서대로
    하나씩 소비된다 (findings 호출 -> revision 호출 순서). 다 쓰면 마지막 걸 반복한다."""

    def __init__(self, responses=None, exc=None):
        self._responses = responses or [("{}", "stop")]
        self._exc = exc
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc:
            raise self._exc
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        content, finish_reason = self._responses[idx]
        return _FakeResponse(content, finish_reason=finish_reason)

    @property
    def last_kwargs(self):
        return self.calls[-1] if self.calls else None


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, content=None, responses=None, exc=None, finish_reason="stop"):
        if responses is None:
            responses = [(content, finish_reason)] if content is not None else None
        self.chat = _FakeChat(_FakeCompletions(responses=responses, exc=exc))


def test_review_with_llm_fills_in_rule_fix_and_adds_new_finding(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    findings_response = (
        '{"new_findings": [{"severity": "warning", "message": "모호한 표현", '
        '"suggestion": "이것 -> 배포 스크립트", "guideline": "core-1"}], '
        '"rule_fixes": [{"index": 0, "fix": "alt=\\"배포 아키텍처 다이어그램\\""}]}'
    )
    fake_client = _FakeClient(responses=[(findings_response, "stop"), ("# 수정본 전체", "stop")])
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    rule_suggestions = [make_rule_suggestion(suggestion="alt 텍스트를 추가하세요.")]
    result = review_with_llm(make_page("<p>이거 해두세요.</p>"), rule_suggestions=rule_suggestions)

    assert len(result.suggestions) == 2
    fixed_rule_suggestion = next(s for s in result.suggestions if s.rule_id == "missing-alt-text")
    assert fixed_rule_suggestion.suggestion == 'alt="배포 아키텍처 다이어그램"'
    new_finding = next(s for s in result.suggestions if s.rule_id == "llm-review")
    assert new_finding.guideline_id == "core-1"
    assert result.revised_document == "# 수정본 전체"
    assert len(fake_client.chat.completions.calls) == 2
    assert all(c["model"] == "qwen2.5-32b-instruct" for c in fake_client.chat.completions.calls)


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


# ---- review_findings_with_llm / generate_revision (독립 호출) ----------


def test_review_findings_with_llm_returns_rule_suggestions_unchanged_when_not_configured(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    rule_suggestions = [make_rule_suggestion(suggestion="원래 조언")]
    result = review_findings_with_llm(make_page(), rule_suggestions=rule_suggestions)
    assert result == rule_suggestions


def test_review_findings_with_llm_does_not_call_revision(monkeypatch):
    # "AI 분석" 버튼은 findings만 실행하고 수정본 생성 호출은 하지 않아야
    # 한다 - 그래야 두 단계가 독립적으로 재시도 가능하다.
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    fake_client = _FakeClient(content='{"new_findings": [], "rule_fixes": []}')
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    review_findings_with_llm(make_page("<p>본문</p>"), rule_suggestions=[])

    assert len(fake_client.chat.completions.calls) == 1


def test_generate_revision_returns_error_when_not_configured(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    revised, error = generate_revision(make_page(), [])
    assert revised is None
    assert error is not None


def test_generate_revision_returns_error_when_model_missing(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    revised, error = generate_revision(make_page(), [])
    assert revised is None
    assert "LLM_MODEL" in error


def test_generate_revision_succeeds_independently_of_findings(monkeypatch):
    # 최종 수정본 제안 버튼은 findings 없이(빈 리스트) 호출해도 동작해야
    # 한다 - AI 분석을 먼저 안 돌리고 바로 눌러도 된다는 뜻.
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    fake_client = _FakeClient(content="# 다시 쓴 문서")
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    revised, error = generate_revision(make_page("<p>본문</p>"), [])

    assert revised == "# 다시 쓴 문서"
    assert error is None
    assert len(fake_client.chat.completions.calls) == 1


def test_generate_revision_truncation_error_advises_increasing_not_decreasing(monkeypatch):
    # 응답이 max_tokens에 걸려 잘린 경우(finish_reason="length")의 해결책은
    # LLM_MAX_OUTPUT_TOKENS를 "늘리는" 것이다 - 반대로 줄이라고 안내하면
    # 사용자가 계속 잘리는 값으로 다시 시도하게 된다(실제로 겪은 문제).
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    fake_client = _FakeClient(content="잘린 응답", finish_reason="length")
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    revised, error = generate_revision(make_page("<p>본문</p>"), [])

    assert revised is None
    assert "늘려" in error
    assert "작게" not in error  # 예전 문구("작게 조정")가 다시 섞여 들어가지 않았는지 확인


def test_generate_revision_can_retry_after_failure_without_findings_call(monkeypatch):
    # "실패해도 그것만 다시 시도" 요구사항: 실패한 뒤 다시 호출해도
    # findings 호출 없이 generate_revision만 다시 도는지 확인한다.
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")

    failing_client = _FakeClient(exc=ConnectionError("일시적 오류"))
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: failing_client)
    revised, error = generate_revision(make_page("<p>본문</p>"), [])
    assert revised is None
    assert "일시적 오류" in error

    succeeding_client = _FakeClient(content="# 재시도 성공")
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: succeeding_client)
    revised, error = generate_revision(make_page("<p>본문</p>"), [])
    assert revised == "# 재시도 성공"
    assert error is None


def test_review_with_llm_findings_call_uses_fixed_budget_regardless_of_document_length(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    monkeypatch.delenv("LLM_MAX_OUTPUT_TOKENS", raising=False)
    fake_client = _FakeClient(responses=[('{"new_findings": [], "rule_fixes": []}', "stop"), ("x", "stop")])
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    long_html = "<p>" + ("가나다라마바사아자차카타파하 " * 500) + "</p>"
    review_with_llm(make_page(long_html))

    findings_call, revision_call = fake_client.chat.completions.calls
    assert findings_call["max_tokens"] == 4096  # 찾기/수정안 호출은 문서 길이와 무관하게 고정 예산
    assert revision_call["max_tokens"] > 4096  # 수정본 호출은 문서가 길면 늘어남


def test_review_with_llm_revision_call_uses_larger_explicit_max_output_tokens(monkeypatch):
    """명시적으로 지정한 값이 문서 길이 기반 추정치보다 크면 그 값을 그대로 쓴다."""
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "50000")
    fake_client = _FakeClient(responses=[('{"new_findings": [], "rule_fixes": []}', "stop"), ("x", "stop")])
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    review_with_llm(make_page())  # 아주 짧은 문서라 추정치는 4096 수준

    findings_call, revision_call = fake_client.chat.completions.calls
    assert revision_call["max_tokens"] == 50000


def test_review_with_llm_revision_call_ignores_smaller_explicit_max_output_tokens(monkeypatch):
    """명시적으로 지정한 값이 문서 길이 기반 추정치보다 작으면(예: .env.example의
    예시 값 4096을 그대로 켜둔 경우), 추정치 쪽을 써서 다시 잘리지 않게 한다."""
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "4096")
    fake_client = _FakeClient(responses=[('{"new_findings": [], "rule_fixes": []}', "stop"), ("x", "stop")])
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    long_html = "<p>" + ("가나다라마바사아자차카타파하 " * 500) + "</p>"
    review_with_llm(make_page(long_html))

    findings_call, revision_call = fake_client.chat.completions.calls
    assert revision_call["max_tokens"] > 4096


def test_review_with_llm_raises_clear_error_when_findings_response_truncated(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    fake_client = _FakeClient(content='{"new_findings": [], "rule_fixes"', finish_reason="length")
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    with pytest.raises(LLMReviewError, match="잘렸습니다"):
        review_with_llm(make_page())


def test_review_with_llm_keeps_suggestions_when_revision_call_truncated(monkeypatch):
    """수정본(2번째 호출) 생성이 중간에 잘려도, 이미 성공한 findings/fixes(1번째
    호출) 결과는 잃지 않고 revised_document만 None이어야 한다."""
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    findings_response = (
        '{"new_findings": [], "rule_fixes": [{"index": 0, "fix": "alt=\\"배포 아키텍처 다이어그램\\""}]}'
    )
    fake_client = _FakeClient(responses=[(findings_response, "stop"), ("잘린 수정본...", "length")])
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    rule_suggestions = [make_rule_suggestion(suggestion="alt 텍스트를 추가하세요.")]
    result = review_with_llm(make_page("<p>본문</p>"), rule_suggestions=rule_suggestions)

    assert result.suggestions[0].suggestion == 'alt="배포 아키텍처 다이어그램"'
    assert result.revised_document is None
    # 실패 사유가 리포트에 남아야 서버 로그 없이도 원인을 알 수 있다.
    error_entry = next(s for s in result.suggestions if s.rule_id == "llm-revision-error")
    assert "잘렸습니다" in error_entry.suggestion


def test_review_with_llm_keeps_suggestions_when_revision_call_raises(monkeypatch):
    """수정본 호출 자체가 예외를 던져도(연결 오류 등) findings/fixes 결과는 유지돼야 한다."""
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")

    call_count = {"n": 0}

    class _FlakyClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    call_count["n"] += 1
                    if call_count["n"] == 1:
                        return _FakeResponse('{"new_findings": [], "rule_fixes": []}')
                    raise ConnectionError("수정본 생성 중 연결 실패")

    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: _FlakyClient())

    result = review_with_llm(make_page("<p>본문</p>"))

    assert result.revised_document is None
    assert call_count["n"] == 2
    error_entry = next(s for s in result.suggestions if s.rule_id == "llm-revision-error")
    assert "연결 실패" in error_entry.suggestion


def test_review_with_llm_retries_findings_call_once_after_transient_failure(monkeypatch):
    """findings 호출이 첫 시도에 실패해도(타임아웃 등), 재시도해서 성공하면
    결과가 정상적으로 반환돼야 한다 - 이게 "같은 문서인데 가끔 확인 불가로
    나온다"는 플레이키니스를 줄이는 핵심 메커니즘이다."""
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")

    call_count = {"n": 0}

    class _FlakyThenOkClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    call_count["n"] += 1
                    if call_count["n"] == 1:
                        raise TimeoutError("일시적인 타임아웃")
                    return _FakeResponse('{"new_findings": [], "rule_fixes": []}')

    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: _FlakyThenOkClient())

    result = review_with_llm(make_page())

    assert result.suggestions == []
    # findings 재시도(2회) + revision 호출(1회) = 3번 호출됐어야 함
    assert call_count["n"] == 3


def test_review_with_llm_gives_up_after_max_findings_attempts(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    fake_client = _FakeClient(exc=TimeoutError("계속 타임아웃"))
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    with pytest.raises(LLMReviewError):
        review_with_llm(make_page())

    from ai_friendly_doc.llm_review import FINDINGS_MAX_ATTEMPTS

    assert len(fake_client.chat.completions.calls) == FINDINGS_MAX_ATTEMPTS


def test_findings_max_output_tokens_scales_with_rule_violation_count():
    from ai_friendly_doc.llm_review import DEFAULT_MAX_OUTPUT_TOKENS, _findings_max_output_tokens

    few = _findings_max_output_tokens([make_rule_suggestion()])
    many = _findings_max_output_tokens([make_rule_suggestion() for _ in range(30)])

    assert few >= DEFAULT_MAX_OUTPUT_TOKENS
    assert many > few  # 위반 항목이 많으면 예산도 더 커야 함


def test_review_with_llm_uses_zero_temperature_for_determinism(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    fake_client = _FakeClient(responses=[('{"new_findings": [], "rule_fixes": []}', "stop"), ("x", "stop")])
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    review_with_llm(make_page())

    findings_call, revision_call = fake_client.chat.completions.calls
    assert findings_call["temperature"] == 0.0
    assert revision_call["temperature"] == 0.0


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
