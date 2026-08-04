from ai_friendly_doc.parser import parse_storage_html
from ai_friendly_doc.rules import (
    AmbiguousLinkTextRule,
    HeadingHierarchySkipRule,
    LongParagraphRule,
    MissingAltTextRule,
    MissingH1Rule,
    MissingTableHeaderRule,
)


def parse(html: str):
    return parse_storage_html("테스트 문서", html)


def test_heading_hierarchy_skip_detected():
    doc = parse("<h1>제목</h1><h3>바로 하위</h3>")
    suggestions = HeadingHierarchySkipRule().check(doc)
    assert len(suggestions) == 1
    assert "H1" in suggestions[0].message


def test_heading_hierarchy_no_skip():
    doc = parse("<h1>제목</h1><h2>하위</h2><h3>더 하위</h3>")
    assert HeadingHierarchySkipRule().check(doc) == []


def test_missing_h1_detected():
    doc = parse("<h2>제목</h2><p>내용</p>")
    suggestions = MissingH1Rule().check(doc)
    assert len(suggestions) == 1


def test_missing_h1_not_flagged_when_no_headings():
    doc = parse("<p>제목 없는 문서</p>")
    assert MissingH1Rule().check(doc) == []


def test_missing_table_header_detected():
    html = "<table><tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
    doc = parse(html)
    suggestions = MissingTableHeaderRule().check(doc)
    assert len(suggestions) == 1


def test_table_with_header_not_flagged():
    html = "<table><tbody><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></tbody></table>"
    doc = parse(html)
    assert MissingTableHeaderRule().check(doc) == []


def test_missing_alt_text_detected():
    html = '<ac:image><ri:attachment ri:filename="a.png" /></ac:image>'
    doc = parse(html)
    suggestions = MissingAltTextRule().check(doc)
    assert len(suggestions) == 1
    assert "a.png" in suggestions[0].location


def test_alt_text_present_not_flagged():
    html = '<ac:image ac:alt="설명"><ri:attachment ri:filename="a.png" /></ac:image>'
    doc = parse(html)
    assert MissingAltTextRule().check(doc) == []


def test_ambiguous_link_text_detected():
    html = '<a href="https://example.com">여기</a>'
    doc = parse(html)
    suggestions = AmbiguousLinkTextRule().check(doc)
    assert len(suggestions) == 1


def test_descriptive_link_text_not_flagged():
    html = '<a href="https://example.com">배포 가이드 문서</a>'
    doc = parse(html)
    assert AmbiguousLinkTextRule().check(doc) == []


def test_long_paragraph_detected():
    long_text = " ".join(["단어"] * 150)
    doc = parse(f"<p>{long_text}</p>")
    suggestions = LongParagraphRule().check(doc)
    assert len(suggestions) == 1


def test_short_paragraph_not_flagged():
    doc = parse("<p>짧은 문단입니다.</p>")
    assert LongParagraphRule().check(doc) == []
