import xml.etree.ElementTree as ET

from ai_friendly_doc.confluence_markdown_macro import (
    escape_markdown_link_text,
    markdown_to_confluence_markdown_macro,
)


def test_empty_text_returns_empty_string():
    assert markdown_to_confluence_markdown_macro("") == ""
    assert markdown_to_confluence_markdown_macro("   \n  ") == ""


def test_wraps_text_in_markdown_macro():
    result = markdown_to_confluence_markdown_macro("# 제목\n\n본문입니다.")
    assert result == (
        '<ac:structured-macro ac:name="markdown" ac:schema-version="1">'
        "<ac:plain-text-body><![CDATA[# 제목\n\n본문입니다.]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )


def test_preserves_markdown_syntax_verbatim():
    # 헤딩/목록/표/링크 등 마크다운 문법을 우리가 직접 변환하지 않고 그대로
    # 매크로 본문에 넣어야 한다 - 실제 렌더링은 Confluence의 마크다운
    # 파서가 담당한다.
    md = "1. 첫 단계\n - 세부 A\n2. 두 번째 단계\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    result = markdown_to_confluence_markdown_macro(md)
    assert md in result


def test_escapes_cdata_terminator_inside_text():
    # 본문에 우연히 "]]>"가 들어있으면 CDATA 섹션이 거기서 끊겨 매크로
    # XML 자체가 깨진다 - 표준적인 이스케이프로 안전하게 감싸야 한다.
    md = "코드 예제: <![CDATA[hello]]> 이렇게 씁니다."
    result = markdown_to_confluence_markdown_macro(md)
    assert "]]]]><![CDATA[>" in result
    # 실제로 CDATA를 끊었다가 다시 여는 시퀀스가 "]]>" 자리를 정확히
    # 대체했는지 확인 - 원본 문자열이 그대로 나오면 안 된다(깨진 매크로).
    assert "<![CDATA[hello]]> 이렇게" not in result


def test_cdata_escaping_round_trips_through_real_xml_parser():
    # 가정이 아니라 실제 XML 파서로 파싱해서, 이스케이프된 매크로를 다시
    # 읽었을 때 원본 텍스트가 한 글자도 안 틀리고 그대로 복원되는지 확인한다
    # (여러 번, 문자열 맨 앞/끝에 걸친 경우 포함).
    for md_text in [
        "코드 예제: <![CDATA[hello]]> 그다음 문장",
        "]]>맨 앞에 있는 경우",
        "맨 뒤에 있는 경우]]>",
        "여러 번 나오는 경우]]>첫번째]]>두번째",
    ]:
        macro = markdown_to_confluence_markdown_macro(md_text)
        wrapped = f'<root xmlns:ac="urn:test">{macro}</root>'
        root = ET.fromstring(wrapped)
        body = root.find(".//{urn:test}plain-text-body")
        assert body.text == md_text


def test_escape_markdown_link_text_escapes_brackets_and_backslash():
    assert escape_markdown_link_text("일반 제목") == "일반 제목"
    assert escape_markdown_link_text("대괄호 [있는] 제목") == "대괄호 \\[있는\\] 제목"
    assert escape_markdown_link_text("백슬래시\\문자") == "백슬래시\\\\문자"


# ---- 문단 안 줄바꿈(하드 브레이크) ----------------------------------------


def test_inserts_hard_break_between_consecutive_plain_paragraph_lines():
    # 표준 마크다운은 문단 안의 순수 개행 하나를 공백으로 접어버린다
    # (소프트 브레이크) - 그래서 빈 줄로 안 나뉜 같은 문단 안의 줄은 줄
    # 끝에 "\"를 붙여 마크다운 하드 브레이크로 만들어야 실제 줄바꿈이
    # 살아남는다.
    result = markdown_to_confluence_markdown_macro("첫 번째 줄\n두 번째 줄")
    assert "첫 번째 줄\\\n두 번째 줄" in result


def test_does_not_add_hard_break_across_blank_line():
    result = markdown_to_confluence_markdown_macro("문단 하나\n\n문단 둘")
    assert "문단 하나\\" not in result
    assert "문단 하나\n\n문단 둘" in result


def test_does_not_add_hard_break_around_list_items():
    result = markdown_to_confluence_markdown_macro("설명\n- 목록1\n- 목록2")
    assert "설명\\" not in result
    assert "목록1\\" not in result


def test_does_not_add_hard_break_around_headings():
    result = markdown_to_confluence_markdown_macro("# 제목\n문단 내용")
    assert "제목\\" not in result


def test_does_not_add_hard_break_around_table_rows():
    result = markdown_to_confluence_markdown_macro("설명\n| a | b |\n|---|---|")
    assert "설명\\" not in result


def test_does_not_add_trailing_hard_break_at_end_of_text():
    result = markdown_to_confluence_markdown_macro("마지막 줄")
    assert "마지막 줄\\" not in result
    assert "마지막 줄]]>" in result
