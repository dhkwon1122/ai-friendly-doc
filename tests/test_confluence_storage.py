from ai_friendly_doc.confluence_storage import markdown_to_confluence_storage


def test_empty_text_returns_empty_string():
    assert markdown_to_confluence_storage("") == ""
    assert markdown_to_confluence_storage("   \n  ") == ""


def test_headings_convert_to_h_tags():
    assert markdown_to_confluence_storage("# 제목") == "<h1>제목</h1>"
    assert markdown_to_confluence_storage("## 소제목") == "<h2>소제목</h2>"
    assert markdown_to_confluence_storage("###### 여섯단계") == "<h6>여섯단계</h6>"


def test_plain_paragraph_wraps_in_p_tag():
    assert markdown_to_confluence_storage("그냥 문단입니다.") == "<p>그냥 문단입니다.</p>"


def test_multiline_paragraph_without_blank_line_merges_into_one_p():
    result = markdown_to_confluence_storage("첫 번째 줄\n두 번째 줄")
    assert result == "<p>첫 번째 줄 두 번째 줄</p>"


def test_blank_line_separates_paragraphs():
    result = markdown_to_confluence_storage("문단 하나\n\n문단 둘")
    assert result == "<p>문단 하나</p>\n<p>문단 둘</p>"


def test_unordered_list_converts_to_ul():
    result = markdown_to_confluence_storage("- 항목1\n- 항목2")
    assert result == "<ul><li>항목1</li><li>항목2</li></ul>"


def test_ordered_list_converts_to_ol():
    result = markdown_to_confluence_storage("1. 첫번째\n2. 두번째")
    assert result == "<ol><li>첫번째</li><li>두번째</li></ol>"


def test_table_first_row_becomes_header():
    md = "| 이름 | 나이 |\n| --- | --- |\n| 홍길동 | 30 |"
    result = markdown_to_confluence_storage(md)
    assert result == (
        "<table><tbody>"
        "<tr><th>이름</th><th>나이</th></tr>"
        "<tr><td>홍길동</td><td>30</td></tr>"
        "</tbody></table>"
    )


def test_table_without_separator_row_still_treats_first_row_as_header():
    md = "| 이름 | 나이 |\n| 홍길동 | 30 |"
    result = markdown_to_confluence_storage(md)
    assert result == (
        "<table><tbody>"
        "<tr><th>이름</th><th>나이</th></tr>"
        "<tr><td>홍길동</td><td>30</td></tr>"
        "</tbody></table>"
    )


def test_bold_converts_to_strong():
    assert markdown_to_confluence_storage("**중요한** 내용") == "<p><strong>중요한</strong> 내용</p>"


def test_italic_converts_to_em():
    assert markdown_to_confluence_storage("*강조* 표현") == "<p><em>강조</em> 표현</p>"


def test_inline_code_converts_to_code_tag():
    assert markdown_to_confluence_storage("`변수명`을 확인하세요") == "<p><code>변수명</code>을 확인하세요</p>"


def test_link_converts_to_anchor_tag():
    result = markdown_to_confluence_storage("[문서 보기](https://example.com/page)")
    assert result == '<p><a href="https://example.com/page">문서 보기</a></p>'


def test_special_characters_are_escaped_not_interpreted_as_tags():
    # 원문에 <script> 같은 텍스트가 그대로 있어도 실제 태그로 해석되면 안 된다.
    result = markdown_to_confluence_storage("5 < 10 이고 A & B <script>alert(1)</script>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result
    assert "&amp;" in result
    assert "&lt; 10" in result


def test_mixed_document_with_heading_paragraph_list_and_table():
    md = (
        "# 설치 가이드\n"
        "\n"
        "아래 단계를 따르세요.\n"
        "\n"
        "- 1단계\n"
        "- 2단계\n"
        "\n"
        "| 항목 | 값 |\n"
        "| --- | --- |\n"
        "| A | 1 |\n"
    )
    result = markdown_to_confluence_storage(md)
    assert "<h1>설치 가이드</h1>" in result
    assert "<p>아래 단계를 따르세요.</p>" in result
    assert "<ul><li>1단계</li><li>2단계</li></ul>" in result
    assert "<table><tbody><tr><th>항목</th><th>값</th></tr><tr><td>A</td><td>1</td></tr></tbody></table>" in result
