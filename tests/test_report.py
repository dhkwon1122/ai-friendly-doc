import markdown as md

from ai_friendly_doc.analyzer import PageReport
from ai_friendly_doc.confluence_client import ConfluencePage
from ai_friendly_doc.guidelines import check_guideline_compliance
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
    revision_guideline_compliance=None,
) -> PageReport:
    suggestions = suggestions or []
    return PageReport(
        page=make_page(web_url=web_url),
        suggestions=suggestions,
        guideline_compliance=check_guideline_compliance(suggestions, llm_configured=False),
        original_document="원본 내용",
        revised_document=revised_document,
        revision_guideline_compliance=revision_guideline_compliance,
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


def test_render_page_section_puts_revision_before_guideline_checklist():
    # 이메일/화면에서 가장 궁금해하는 결과물(수정 제안)을 발견 사항 목록보다
    # 먼저 볼 수 있어야 한다.
    section = render_page_section(make_page_report(revised_document="## 수정된 문서 내용"))
    assert section.index("최종 수정본") < section.index("핵심 가이드라인 준수")


def test_revised_document_line_breaks_survive_markdown_to_html_conversion():
    # report.py는 최종 수정본을 ```...``` 펜스드 코드 블록으로 감싸는데,
    # "fenced_code" 확장 없이 markdown.markdown()을 쓰면 이 블록이 코드로
    # 인식되지 않고 일반 문단 취급되어 내부 줄바꿈이 공백으로 뭉개진다
    # (web/app.py에서 이메일 본문을 만들 때 실제로 겪은 문제) - 이 확장이
    # 켜져 있으면 줄바꿈이 살아남는지 확인한다.
    revised = "첫 번째 줄\n두 번째 줄\n세 번째 줄"
    section = render_page_section(make_page_report(revised_document=revised))

    html = md.markdown(section, extensions=["tables", "fenced_code"])

    # <pre>로 감싸져야 브라우저/메일 클라이언트가 공백을 그대로 보존해서
    # 렌더링한다(<pre>가 없으면 텍스트에 \n이 남아 있어도 화면에는 공백
    # 하나로 뭉개져 보인다 - HTML의 기본 공백 처리 규칙 때문).
    assert "<pre>" in html
    assert "첫 번째 줄\n두 번째 줄\n세 번째 줄" in html

    # fenced_code 없이 변환하면(회귀 방지용 대조군) <pre>로 감싸지지 않아서
    # 실제로 표시될 때 줄바꿈이 사라진다.
    html_without_fenced_code = md.markdown(section, extensions=["tables"])
    assert "<pre>" not in html_without_fenced_code


# ---- 가이드라인 표: 점수 미표시 + 수정본 상태 컬럼 -------------------------


def test_guideline_checklist_does_not_show_a_score():
    section = render_page_section(make_page_report())
    assert "점" not in section  # "86점" 같은 점수 표기가 더 이상 없어야 한다
    assert "핵심 가이드라인 준수" in section


def test_guideline_checklist_has_single_status_column_when_no_revision_compliance():
    section = render_page_section(make_page_report(revised_document=None))
    assert "| 가이드라인 | 상태 |" in section
    assert "수정본 상태" not in section


def test_guideline_checklist_adds_revision_status_column_when_revision_verified():
    revision_compliance = check_guideline_compliance([], llm_configured=True, rule_engine_ran=False)
    section = render_page_section(
        make_page_report(revised_document="# 수정본", revision_guideline_compliance=revision_compliance)
    )
    assert "| 가이드라인 | 원본 상태 | 수정본 상태 |" in section
    assert "✅ 준수" in section


def test_summary_table_does_not_include_score_column():
    report = render_report([make_page_report()])
    assert "핵심 가이드 점수" not in report
    assert "점" not in report.split("---")[0]  # 요약 표 부분에는 점수 표기가 없어야 한다
