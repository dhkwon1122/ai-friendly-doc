import pytest

from ai_friendly_doc.confluence_client import ConfluencePage
from ai_friendly_doc.llm_review import (
    LLMReviewError,
    _parse_llm_json,
    _to_suggestions,
    is_llm_configured,
    review_with_llm,
    storage_html_to_plain_text,
)
from ai_friendly_doc.rules import Severity


def make_page(storage_html: str = "<p>본문</p>") -> ConfluencePage:
    return ConfluencePage(
        id="1", title="테스트 문서", space_key="ENG", version=1, storage_html=storage_html, web_url=""
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


def test_plain_text_marks_image_without_alt():
    text = storage_html_to_plain_text('<ac:image><ri:attachment ri:filename="a.png" /></ac:image>')
    assert "대체 텍스트 없음" in text


def test_plain_text_uses_alt_when_present():
    text = storage_html_to_plain_text('<ac:image ac:alt="다이어그램"><ri:attachment /></ac:image>')
    assert "다이어그램" in text


def test_plain_text_truncates_when_too_long():
    html = "<p>" + ("가" * 100) + "</p>"
    text = storage_html_to_plain_text(html, max_chars=20)
    assert len(text) <= 20 + len("\n\n...(문서가 길어 이하 생략됨)")
    assert "생략됨" in text


# ---- _parse_llm_json -----------------------------------------------------


def test_parse_llm_json_plain_array():
    assert _parse_llm_json('[{"severity": "info"}]') == [{"severity": "info"}]


def test_parse_llm_json_code_fenced():
    raw = '```json\n[{"severity": "warning"}]\n```'
    assert _parse_llm_json(raw) == [{"severity": "warning"}]


def test_parse_llm_json_extracts_array_from_surrounding_prose():
    raw = '여기 결과입니다:\n[{"severity": "critical"}]\n감사합니다.'
    assert _parse_llm_json(raw) == [{"severity": "critical"}]


def test_parse_llm_json_raises_on_garbage():
    with pytest.raises(LLMReviewError):
        _parse_llm_json("이건 JSON이 아닙니다")


def test_parse_llm_json_raises_when_not_a_list():
    with pytest.raises(LLMReviewError):
        _parse_llm_json('{"not": "a list"}')


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


# ---- review_with_llm (네트워크 호출은 모두 모킹) ----------------------------


def test_review_with_llm_returns_empty_when_not_configured(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert is_llm_configured() is False
    assert review_with_llm(make_page()) == []


def test_review_with_llm_raises_when_model_missing(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(LLMReviewError):
        review_with_llm(make_page())


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content=None, exc=None):
        self._content = content
        self._exc = exc
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self._exc:
            raise self._exc
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, content=None, exc=None):
        self.chat = _FakeChat(_FakeCompletions(content=content, exc=exc))


def test_review_with_llm_success(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.internal:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-32b-instruct")
    fake_client = _FakeClient(content='[{"severity": "warning", "message": "모호한 표현", "suggestion": "구체화"}]')
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    suggestions = review_with_llm(make_page("<p>이거 해두세요.</p>"))

    assert len(suggestions) == 1
    assert suggestions[0].rule_id == "llm-review"
    assert suggestions[0].severity == Severity.WARNING
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
    fake_client = _FakeClient(content="[]")
    monkeypatch.setattr("ai_friendly_doc.llm_review._client", lambda: fake_client)

    assert review_with_llm(make_page("")) == []
    assert fake_client.chat.completions.last_kwargs is None
