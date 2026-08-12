"""LLM이 만드는 평문 수정본(마크다운과 거의 같은 문법: 제목 #, 목록 -,
표 |a|b|, 링크 [text](url) 등)을 Confluence의 "Markdown" 매크로로 감싼다.

예전에는(구 confluence_storage.py) 이 평문을 파이썬 코드로 직접 Confluence
storage format(XHTML) 태그(<h1>, <ul>, <table> 등)로 기계적으로 변환했다.
그런데 실제로 Confluence 소스 편집기에 붙여넣어보면 표/중첩 목록처럼
복잡한 구조가 얽힐 때 재현이 잘 안 되는 경우가 많았다 - 예를 들어 번호
목록 사이에 표가 끼는 경우를 여러 번 고쳐도 계속 새로운 예외 상황이
나왔다. 마크다운 문법 전체를 우리가 직접, 완벽하게 XHTML로 재현하려는
접근 자체에 한계가 있었다.

그래서 접근을 바꿨다: 우리가 직접 XHTML 태그를 만들지 않고, 평문을 그대로
Confluence 내장 "Markdown" 매크로(ac:structured-macro ac:name="markdown")
본문에 감싸 넣는다. 실제 렌더링은 Confluence 자신의 마크다운 파서가
하므로, 헤딩/목록/표/링크 문법을 우리가 하나하나 XHTML로 재현하다가
놓치는 예외 상황이 원천적으로 없어진다.

이 매크로는 Confluence Cloud/Server/DC에 흔히 설치되는 애드온(예:
"Markdown Macro for Confluence")이 제공한다 - 대상 인스턴스에 이 매크로가
없으면 붙여넣었을 때 "Unknown macro" 경고가 뜬다.
"""

from __future__ import annotations

import re

_MACRO_OPEN = '<ac:structured-macro ac:name="markdown" ac:schema-version="1">'
_BODY_OPEN = "<ac:plain-text-body><![CDATA["
_BODY_CLOSE = "]]></ac:plain-text-body>"
_MACRO_CLOSE = "</ac:structured-macro>"

_HEADING_RE = re.compile(r"^#{1,6}\s+.*$")
_LIST_ITEM_RE = re.compile(r"^[-*]\s+.*$")
_ORDERED_ITEM_RE = re.compile(r"^\d+\.\s+.*$")
_TABLE_ROW_RE = re.compile(r"^\|.+\|\s*$")


def _is_plain_paragraph_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return not (
        _HEADING_RE.match(stripped)
        or _LIST_ITEM_RE.match(stripped)
        or _ORDERED_ITEM_RE.match(stripped)
        or _TABLE_ROW_RE.match(stripped)
    )


def _insert_hard_line_breaks(text: str) -> str:
    """빈 줄로 안 나뉜 같은 문단 안의 줄바꿈을 마크다운 하드 브레이크로
    바꾼다.

    표준 마크다운(Confluence의 Markdown 매크로 포함)은 문단 안의 순수
    개행 하나를 줄바꿈이 아니라 그냥 공백으로 접어버린다(소프트 브레이크).
    그래서 원본 문서에 있던 줄바꿈이 우리가 손대지 않은 평문을 그대로
    넘기면 사라진다. 마크다운에서 줄바꿈을 강제하는 표준 방법은 줄 끝에
    역슬래시를 붙이는 것이다(공백 두 개짜리 방법은 우리 쪽 처리 과정에서
    trailing whitespace가 잘려나가기 쉬워 덜 안전하다).

    제목/목록/표처럼 이미 자기 줄에서 독립된 블록으로 인식되는 줄은 건드리지
    않는다 - 그 경계는 마크다운 문법 자체가 이미 처리하므로 하드 브레이크가
    필요 없다. 오직 "평범한 문단 줄 바로 다음에 또 평범한 문단 줄이 오는"
    경우에만 사이에 하드 브레이크를 넣는다.
    """
    lines = text.splitlines()
    n = len(lines)
    for i in range(n - 1):
        if _is_plain_paragraph_line(lines[i]) and _is_plain_paragraph_line(lines[i + 1]):
            lines[i] = lines[i].rstrip() + "\\"
    return "\n".join(lines)


def _escape_cdata(text: str) -> str:
    # CDATA 섹션은 "]]>"가 나오는 순간 그 지점에서 끝나버린다. 마크다운
    # 본문에 우연히 그 문자열이 들어있어도(예: 코드 예제) 매크로 XML 자체가
    # 깨지지 않도록, CDATA를 잠깐 끊었다가 리터럴 ">" 하나를 두고 새
    # CDATA로 다시 잇는 표준적인 이스케이프 방법을 쓴다.
    return text.replace("]]>", "]]]]><![CDATA[>")


def markdown_to_confluence_markdown_macro(text: str) -> str:
    """평문 마크다운을 Confluence "Markdown" 매크로 XML로 감싼다.

    빈 문자열이면 빈 문자열을 반환한다.
    """
    if not text or not text.strip():
        return ""
    with_breaks = _insert_hard_line_breaks(text)
    return f"{_MACRO_OPEN}{_BODY_OPEN}{_escape_cdata(with_breaks)}{_BODY_CLOSE}{_MACRO_CLOSE}"


def escape_markdown_link_text(text: str) -> str:
    """마크다운 링크 문법 [text](url) 안의 text 자리에 넣을 때 안전하도록
    이스케이프한다. 이스케이프 문자 자체와, 링크 텍스트를 조기에 끝내버리는
    "["/"]"만 다룬다 - 원본 문서 제목처럼 사람이 자유롭게 지은 텍스트가
    이 자리에 들어가기 때문에, 그 안에 있을 수 있는 대괄호가 마크다운
    링크 문법을 깨지 않게 막는다.
    """
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
