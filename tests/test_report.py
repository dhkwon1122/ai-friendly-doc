from ai_friendly_doc.analyzer import PageReport
from ai_friendly_doc.confluence_client import ConfluencePage
from ai_friendly_doc.guidelines import score_document
from ai_friendly_doc.report import render_page_section, render_report
from ai_friendly_doc.rules import Severity, Suggestion


def make_page(web_url: str = "https://example.atlassian.net/wiki/spaces/ENG/pages/123") -> ConfluencePage:
    return ConfluencePage(
        id="123", title="테스트 문서", space_key="ENG", version=1, storage_html="<p>본문</p>", web_url=web_url
    )


def make_page_report(
    suggestions: list[Suggestion] | None = None,
    revised_document: str | None = None,
    web_url: str = "https://example.atlassian.net/wiki/spaces/ENG/pages/123",
) -> PageReport:
    suggestions = suggestions or []
    return PageReport(
        page=make_page(web_url=web_url),
        suggestions=suggestions,
        guideline_score=score_document(suggestions, llm_configured=False),
        original_document="원본 내용",
        revised_document=revised_document,
    )


def test_render_page_section_renders_original_url_as_markdown_link():
    section = render_page_section(make_page_report())
    assert "[https://example.atlassian.net/wiki/spaces/ENG/pages/123](https://example.atlassian.net/wiki/spaces/ENG/pages/123)" in section


def test_render_page_section_omits_url_line_when_missing():
    section = render_page_section(make_page_report(web_url=""))
    assert "원본:" not in section


def test_render_page_section_includes_revised_document_when_present():
    section = render_page_section(make_page_report(revised_document="## 수정된 문서 내용"))
    assert "최종 수정본" in section
    assert "## 수정된 문서 내용" in section


def test_render_page_section_shows_notice_when_revised_document_missing():
    section = render_page_section(make_page_report(revised_document=None))
    assert "최종 수정본" in section
    assert "만들어지지 않았습니다" in section


def test_render_report_includes_revision_for_every_page():
    reports = [make_page_report(revised_document="# 문서 A 수정본"), make_page_report(revised_document=None)]
    report = render_report(reports)
    assert "# 문서 A 수정본" in report
    assert report.count("최종 수정본") == 2
