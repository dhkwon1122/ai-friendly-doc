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
_ORDERED_ITEM_RE = re.compile(r"^\d+\.\s+(.*)$")
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
            items = []
            while i < n:
                current = lines[i].rstrip()
                m = _LIST_ITEM_RE.match(current) if tag == "ul" else _ORDERED_ITEM_RE.match(current)
                if not m:
                    break
                items.append(f"<li>{_inline_to_storage(m.group(1).strip())}</li>")
                i += 1
            parts.append(f"<{tag}>{''.join(items)}</{tag}>")
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
        paragraph_text = " ".join(p.strip() for p in paragraph_lines)
        parts.append(f"<p>{_inline_to_storage(paragraph_text)}</p>")

    return "\n".join(parts)
