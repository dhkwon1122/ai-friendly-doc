"""LLM이 만드는 단순 평문 수정본(제목 #, 목록 -, 표 |a|b|)을 Confluence
storage format(XHTML)으로 기계적으로 변환한다.

LLM에게 직접 Confluence storage format(XHTML)을 만들게 하지 않는 이유:
문법이 조금이라도 깨지면(태그가 안 닫히거나, 특수문자가 이스케이프 안 되는
등) Confluence 소스 편집기에 붙여넣었을 때 페이지 전체가 깨진다 - 특히
자체 호스팅하는 작은 모델일수록 복잡한 마크업 문법을 안정적으로 못 지킨다.
그래서 LLM은 지금처럼 단순하고 안정적으로 만들 수 있는 평문만 계속
만들게 하고, 이 모듈이 그 결과를 결정적으로(항상 같은 규칙으로, 실패
없이) 변환한다.

표 병합/이미지/매크로 등 Confluence 고유 요소는 지원하지 않는다 -애초에
원본을 평문으로 바꾸는 단계(llm_review.storage_html_to_plain_text)에서부터
그 정보가 빠져 있어서 복원할 수 없다. 기본 구조(제목/문단/목록/표/굵게/
기울임/링크/인라인 코드)만 지원한다.
"""

from __future__ import annotations

import html
import re

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_ITEM_RE = re.compile(r"^[-*]\s+(.*)$")
_ORDERED_ITEM_RE = re.compile(r"^(\d+)\.\s+(.*)$")
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]+\|?$")

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`]+?)`")


def _inline_to_storage(text: str) -> str:
    # 먼저 전체를 이스케이프해서 원문에 있던 <, >, & 등이 실제 태그로
    # 오인되지 않게 한 뒤(따옴표도 함께 이스케이프돼 href 값에 들어가도
    # 안전하다), 그 위에 마크다운 인라인 문법을 실제 태그로 치환한다 -
    # 이스케이프가 먼저이므로 이후에 넣는 태그들은 안전하게 그대로 남는다.
    escaped = html.escape(text)
    escaped = _LINK_RE.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', escaped)
    escaped = _BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", escaped)
    escaped = _ITALIC_RE.sub(lambda m: f"<em>{m.group(1)}</em>", escaped)
    escaped = _CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", escaped)
    return escaped


def _match_item(line: str, tag: str) -> tuple[int | None, str] | None:
    """line이 tag("ul"/"ol") 종류의 목록 항목이면 (번호, 항목 텍스트)를
    반환한다. ul은 번호가 없으므로 번호 자리에 None이 온다. 매칭 안 되면
    None.
    """
    if tag == "ul":
        m = _LIST_ITEM_RE.match(line)
        if not m:
            return None
        return None, m.group(1).strip()
    m = _ORDERED_ITEM_RE.match(line)
    if not m:
        return None
    return int(m.group(1)), m.group(2).strip()


def _parse_list(lines: list[str], start: int, n: int, tag: str) -> tuple[str, int]:
    """항목 사이에 들여쓰기된 하위 목록이나 빈 줄이 끼어 있어도 하나의
    <ol>/<ul>로 계속 묶는다.

    항목 하나가 끝날 때마다 새 <ol>/<ul>을 만들면, Confluence는 그 목록을
    다시 1번부터 번호를 매기기 때문에(각 항목이 전부 "1."로 보이는 문제)
    원본에 있던 순서가 뒤죽박죽으로 보인다. LLM이 만드는 수정본은 종종
    번호 항목 아래에 들여쓴 "- " 하위 설명을 붙이는데(하위 목록), 그런
    하위 목록은 바로 위 항목의 <li> 안에 중첩된 목록으로 넣고, 상위 번호
    목록 자체는 계속 이어간다.

    다만 표/문단처럼 목록 항목이 아닌 다른 블록이 번호 항목 사이에 끼는
    경우까지 전부 여기서 미리 예측해 병합할 수는 없다(끼어들 수 있는
    블록 종류가 너무 다양하다). 그래서 여기서 병합하지 못해 결국 별도의
    <ol>로 갈라지더라도, 그 <ol>이 실제로 몇 번부터 시작하는 항목인지는
    소스에 적힌 숫자(예: "2. ")에서 그대로 읽어 <ol start="N">으로
    표시한다 - 병합 여부와 무관하게, Confluence가 항상 1번부터 다시
    매기는 문제 자체를 원천적으로 막는다.
    """
    items: list[str] = []
    i = start
    first_number: int | None = None
    while i < n:
        current = lines[i].rstrip()
        matched = _match_item(current, tag)
        if matched is None:
            break
        number, text = matched
        if first_number is None:
            first_number = number
        item_html = _inline_to_storage(text)
        i += 1

        # 항목 바로 아래에 들여쓰기된 하위 목록이 있으면(원래 정규식은
        # 들여쓰기가 없는 줄만 매칭하므로 들여쓰인 줄은 위에서 안 걸린다)
        # 현재 항목 안에 중첩된 목록으로 넣는다.
        nested_items: list[str] = []
        nested_tag: str | None = None
        while i < n:
            nested_raw = lines[i].rstrip()
            if not nested_raw.strip():
                break
            stripped = nested_raw.lstrip()
            if len(stripped) == len(nested_raw):
                break  # 들여쓰기가 없다 - 다음 형제 항목이거나 다른 블록
            nested_ul = _match_item(stripped, "ul")
            nested_ol = _match_item(stripped, "ol")
            if nested_ul is None and nested_ol is None:
                break
            current_nested_tag = "ul" if nested_ul is not None else "ol"
            if nested_tag is None:
                nested_tag = current_nested_tag
            elif nested_tag != current_nested_tag:
                break  # 하위 목록 종류가 섞이면 더 복잡해지므로 여기서 중첩을 멈춘다
            _, nested_text = nested_ul if nested_ul is not None else nested_ol
            nested_items.append(f"<li>{_inline_to_storage(nested_text)}</li>")
            i += 1

        if nested_items:
            item_html += f"<{nested_tag}>{''.join(nested_items)}</{nested_tag}>"
        items.append(f"<li>{item_html}</li>")

        # 다음 항목 앞에 빈 줄이 하나 있어도(느슨한 목록 스타일) 그다음 줄이
        # 같은 종류의 항목이면 계속 같은 목록으로 묶는다. 다른 내용이면 빈
        # 줄을 그대로 문단 구분으로 남겨야 하므로 여기서 건드리지 않는다.
        if i < n and not lines[i].strip():
            if i + 1 < n and _match_item(lines[i + 1].rstrip(), tag) is not None:
                i += 1
            else:
                break

    start_attr = f' start="{first_number}"' if tag == "ol" and first_number not in (None, 1) else ""
    return f"<{tag}{start_attr}>{''.join(items)}</{tag}>", i


def _render_table(table_lines: list[str]) -> str:
    rows = []
    for raw_line in table_lines:
        if _TABLE_SEPARATOR_RE.match(raw_line.strip()):
            continue  # 마크다운 헤더 구분선(|---|---|)은 건너뛴다
        cells = [c.strip() for c in raw_line.strip().strip("|").split("|")]
        rows.append(cells)

    if not rows:
        return ""

    row_html = ["<tr>" + "".join(f"<th>{_inline_to_storage(c)}</th>" for c in rows[0]) + "</tr>"]
    for cells in rows[1:]:
        row_html.append("<tr>" + "".join(f"<td>{_inline_to_storage(c)}</td>" for c in cells) + "</tr>")

    return "<table><tbody>" + "".join(row_html) + "</tbody></table>"


def markdown_to_confluence_storage(text: str) -> str:
    """report.py가 만드는 단순 평문(제목 #, 목록 -, 표 |a|b|)을 Confluence
    storage format(XHTML)으로 변환한다. 빈 문자열이면 빈 문자열을 반환한다.
    """
    if not text or not text.strip():
        return ""

    lines = text.splitlines()
    parts: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].rstrip()

        if not line.strip():
            i += 1
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = _inline_to_storage(heading_match.group(2).strip())
            parts.append(f"<h{level}>{heading_text}</h{level}>")
            i += 1
            continue

        if _TABLE_ROW_RE.match(line):
            table_lines = []
            while i < n and _TABLE_ROW_RE.match(lines[i].rstrip()):
                table_lines.append(lines[i].rstrip())
                i += 1
            parts.append(_render_table(table_lines))
            continue

        list_match = _LIST_ITEM_RE.match(line)
        ordered_match = _ORDERED_ITEM_RE.match(line)
        if list_match or ordered_match:
            tag = "ul" if list_match else "ol"
            list_html, i = _parse_list(lines, i, n, tag)
            parts.append(list_html)
            continue

        # 일반 문단 - 다음 빈 줄/다른 블록 시작 전까지 한 문단으로 이어붙인다.
        paragraph_lines = [line]
        i += 1
        while (
            i < n
            and lines[i].strip()
            and not _HEADING_RE.match(lines[i])
            and not _TABLE_ROW_RE.match(lines[i])
            and not _LIST_ITEM_RE.match(lines[i])
            and not _ORDERED_ITEM_RE.match(lines[i])
        ):
            paragraph_lines.append(lines[i].rstrip())
            i += 1
        # 줄바꿈은 공백으로 합치지 않고 <br/>로 보존한다 - HTML은 순수 개행을
        # 공백으로 접어버리므로(white-space 접기), 소스에 \n을 그대로 남겨둬도
        # 붙여넣은 결과에서는 줄바꿈 없이 한 줄로 붙어버린다. 명시적으로
        # <br/> 태그를 넣어야 실제로 줄이 나뉜다.
        paragraph_html = "<br/>".join(_inline_to_storage(p.strip()) for p in paragraph_lines)
        parts.append(f"<p>{paragraph_html}</p>")

    # 블록 사이에 개행을 넣지 않는다 - Confluence 소스 편집기에 붙여넣을 때
    # 태그 사이의 순수 공백/개행이 예상 못한 빈 줄바꿈으로 해석되는 경우가
    # 있어서, 블록 태그(<p>, <h1>...) 자체가 구분자 역할을 하도록 이어붙인다.
    return "".join(parts)
