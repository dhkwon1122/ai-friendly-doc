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


def test_multiline_paragraph_without_blank_line_keeps_line_breaks():
    # 빈 줄로 안 나뉜 같은 문단 안의 줄바꿈도 공백으로 뭉개지 않고 <br/>로
    # 보존해야 한다 - HTML은 순수 개행을 공백으로 접어버리므로, <br/> 없이는
    # 붙여넣었을 때 줄바꿈이 사라진다.
    result = markdown_to_confluence_storage("첫 번째 줄\n두 번째 줄")
    assert result == "<p>첫 번째 줄<br/>두 번째 줄</p>"


def test_blank_line_separates_paragraphs():
    result = markdown_to_confluence_storage("문단 하나\n\n문단 둘")
    assert result == "<p>문단 하나</p><p>문단 둘</p>"


def test_unordered_list_converts_to_ul():
    result = markdown_to_confluence_storage("- 항목1\n- 항목2")
    assert result == "<ul><li>항목1</li><li>항목2</li></ul>"


def test_ordered_list_converts_to_ol():
    result = markdown_to_confluence_storage("1. 첫번째\n2. 두번째")
    assert result == "<ol><li>첫번째</li><li>두번째</li></ol>"


def test_ordered_list_with_indented_sub_bullets_stays_one_list():
    # 번호 항목 아래에 들여쓰기된 "- " 하위 설명이 끼어 있어도 별도의 새
    # <ol>이 되면 안 된다 - 새 <ol>마다 Confluence가 다시 1번부터 번호를
    # 매겨서 모든 항목이 "1."로 보이는 문제가 생긴다. 하위 목록은 바로 위
    # 항목의 <li> 안에 중첩된 <ul>로 들어가고, 번호 목록 자체는 이어져야 한다.
    md = "1. 첫 단계\n - 세부 A\n - 세부 B\n2. 두 번째 단계\n3. 세 번째 단계"
    result = markdown_to_confluence_storage(md)
    assert result == (
        "<ol>"
        "<li>첫 단계<ul><li>세부 A</li><li>세부 B</li></ul></li>"
        "<li>두 번째 단계</li>"
        "<li>세 번째 단계</li>"
        "</ol>"
    )


def test_ordered_list_with_blank_lines_between_items_stays_one_list():
    # 항목 사이에 빈 줄이 하나씩 있는 느슨한(loose) 목록 스타일도 같은
    # 이유로 하나의 <ol>로 묶여야 한다.
    md = "1. 항목 하나\n\n2. 항목 둘\n\n3. 항목 셋"
    result = markdown_to_confluence_storage(md)
    assert result == "<ol><li>항목 하나</li><li>항목 둘</li><li>항목 셋</li></ol>"


def test_ordered_list_ends_when_followed_by_unrelated_paragraph():
    md = "1. 항목 하나\n2. 항목 둘\n\n그냥 문단입니다."
    result = markdown_to_confluence_storage(md)
    assert result == "<ol><li>항목 하나</li><li>항목 둘</li></ol><p>그냥 문단입니다.</p>"


def test_ordered_list_resumes_numbering_with_start_attr_when_table_intervenes():
    # 표/문단처럼 목록 항목이 아닌 다른 블록이 번호 항목 사이에 끼는 경우는
    # 미리 전부 예측해서 하나의 <ol>로 병합할 수 없다(끼어들 수 있는 블록
    # 종류가 너무 다양함). 그래서 별도의 <ol>로 갈라지더라도, 소스에 적힌
    # 실제 번호("2. ")를 읽어 <ol start="2">로 이어붙여서 Confluence가
    # 항상 1번부터 다시 매기는 문제 자체를 막아야 한다.
    md = "1. 첫 번째 단계\n\n| 항목 | 값 |\n| --- | --- |\n| a | 1 |\n\n2. 두 번째 단계\n3. 세 번째 단계"
    result = markdown_to_confluence_storage(md)
    assert "<ol><li>첫 번째 단계</li></ol>" in result
    assert '<ol start="2"><li>두 번째 단계</li><li>세 번째 단계</li></ol>' in result


def test_ordered_list_resumes_numbering_with_start_attr_when_paragraph_intervenes():
    md = "1. 첫 번째 단계\n\n설명 문단입니다.\n\n2. 두 번째 단계"
    result = markdown_to_confluence_storage(md)
    assert "<ol><li>첫 번째 단계</li></ol>" in result
    assert '<ol start="2"><li>두 번째 단계</li></ol>' in result


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
