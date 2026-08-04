from ai_friendly_doc.parser import parse_storage_html
from ai_friendly_doc.rules import (
    AmbiguousLinkTextRule,
    ExcessiveMacroRule,
    HeadingHierarchySkipRule,
    LongParagraphRule,
    MergedOrNestedTableRule,
    MissingAltTextRule,
    MissingH1Rule,
    MissingTableHeaderRule,
    PseudoNumberedListRule,
    RelativeTimeExpressionRule,
    VagueHeadingRule,
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


def test_missing_table_header_tagged_core_2():
    html = "<table><tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
    suggestions = MissingTableHeaderRule().check(parse(html))
    assert suggestions[0].guideline_id == "core-2"


def test_ambiguous_link_text_tagged_core_1():
    html = '<a href="https://example.com">여기</a>'
    suggestions = AmbiguousLinkTextRule().check(parse(html))
    assert suggestions[0].guideline_id == "core-1"


def test_relative_time_expression_detected():
    doc = parse("<p>최근에 배포된 버전을 확인하세요.</p>")
    suggestions = RelativeTimeExpressionRule().check(doc)
    assert len(suggestions) == 1
    assert suggestions[0].guideline_id == "core-6"
    assert "최근" in suggestions[0].message


def test_absolute_date_not_flagged():
    doc = parse("<p>2024년 3월에 배포된 버전을 확인하세요.</p>")
    assert RelativeTimeExpressionRule().check(doc) == []


def test_merged_cell_detected():
    html = '<table><tbody><tr><td colspan="2">병합됨</td></tr></tbody></table>'
    suggestions = MergedOrNestedTableRule().check(parse(html))
    assert len(suggestions) == 1
    assert suggestions[0].guideline_id == "extra-2"
    assert "병합" in suggestions[0].message


def test_nested_table_detected():
    html = (
        "<table><tbody><tr><td>"
        "<table><tbody><tr><td>안쪽</td></tr></tbody></table>"
        "</td></tr></tbody></table>"
    )
    suggestions = MergedOrNestedTableRule().check(parse(html))
    assert len(suggestions) == 1
    assert "중첩" in suggestions[0].message


def test_plain_table_not_flagged_for_merge_or_nesting():
    html = "<table><tbody><tr><td>a</td><td>b</td></tr></tbody></table>"
    assert MergedOrNestedTableRule().check(parse(html)) == []


def test_vague_heading_detected():
    doc = parse("<h2>설정</h2>")
    suggestions = VagueHeadingRule().check(doc)
    assert len(suggestions) == 1
    assert suggestions[0].guideline_id == "extra-5"


def test_descriptive_heading_not_flagged():
    doc = parse("<h2>Redis 캐시 설정 가이드</h2>")
    assert VagueHeadingRule().check(doc) == []


def test_pseudo_numbered_list_detected():
    doc = parse("<p>진행 순서는 1) 준비하고 2) 실행하고 3) 확인하면 됩니다.</p>")
    suggestions = PseudoNumberedListRule().check(doc)
    assert len(suggestions) == 1
    assert suggestions[0].guideline_id == "extra-6"


def test_real_ordered_list_not_flagged_by_pseudo_numbered_list_rule():
    # <ol>/<li>로 만든 진짜 리스트는 paragraphs에 안 잡히므로 애초에 대상이 아님
    doc = parse("<ol><li>준비</li><li>실행</li><li>확인</li></ol>")
    assert PseudoNumberedListRule().check(doc) == []


def test_single_inline_number_not_flagged():
    # 번호가 하나뿐이면(나열이 아니면) 굳이 리스트로 바꿀 필요 없음
    doc = parse("<p>1) 항목 하나만 있는 문장입니다.</p>")
    assert PseudoNumberedListRule().check(doc) == []


def test_excessive_macros_detected():
    html = "".join(['<ac:structured-macro ac:name="x"></ac:structured-macro>'] * 9)
    suggestions = ExcessiveMacroRule().check(parse(html))
    assert len(suggestions) == 1
    assert suggestions[0].guideline_id == "extra-7"


def test_few_macros_not_flagged():
    html = '<ac:structured-macro ac:name="code"></ac:structured-macro>'
    assert ExcessiveMacroRule().check(parse(html)) == []
