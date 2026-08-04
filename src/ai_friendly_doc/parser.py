"""Confluence storage format(XHTML)을 규칙 엔진이 다루기 쉬운 구조로 변환한다."""

from __future__ import annotations

from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


@dataclass
class Heading:
    level: int
    text: str
    index: int


@dataclass
class TableInfo:
    index: int
    has_header_row: bool
    row_count: int
    col_count: int
    preceding_heading: str | None
    has_merged_cells: bool = False
    has_nested_table: bool = False


@dataclass
class ImageInfo:
    index: int
    has_alt_text: bool
    alt_text: str
    filename: str | None
    preceding_heading: str | None


@dataclass
class LinkInfo:
    index: int
    text: str
    href: str | None
    preceding_heading: str | None


@dataclass
class ParagraphInfo:
    index: int
    text: str
    word_count: int
    preceding_heading: str | None


@dataclass
class ParsedDoc:
    title: str
    headings: list[Heading] = field(default_factory=list)
    tables: list[TableInfo] = field(default_factory=list)
    images: list[ImageInfo] = field(default_factory=list)
    links: list[LinkInfo] = field(default_factory=list)
    paragraphs: list[ParagraphInfo] = field(default_factory=list)
    macro_count: int = 0  # 문서에 등장하는 ac:structured-macro(로드맵/결정 매트릭스 등) 총 개수


def _has_ancestor(el: Tag, *names: str) -> bool:
    for parent in el.parents:
        if getattr(parent, "name", None) in names:
            return True
    return False


def _link_text(el: Tag) -> str:
    if el.name == "a":
        return el.get_text(strip=True)
    # ac:link: 본문은 ac:plain-text-link-body / ac:link-body 안에 있음
    body = el.find(["ac:plain-text-link-body", "ac:link-body"])
    if body is not None:
        return body.get_text(strip=True)
    ri_page = el.find("ri:page")
    if ri_page is not None:
        return ri_page.get("ri:content-title", "")
    return el.get_text(strip=True)


def parse_storage_html(title: str, storage_html: str) -> ParsedDoc:
    soup = BeautifulSoup(storage_html, "html.parser")
    doc = ParsedDoc(title=title)

    current_heading: str | None = None
    heading_idx = table_idx = image_idx = link_idx = para_idx = 0

    for el in soup.find_all(True):
        name = el.name

        if name in HEADING_LEVELS:
            text = el.get_text(strip=True)
            doc.headings.append(Heading(level=HEADING_LEVELS[name], text=text, index=heading_idx))
            heading_idx += 1
            current_heading = text
            continue

        if name == "table":
            rows = el.find_all("tr")
            has_header = el.find("th") is not None
            col_count = 0
            if rows:
                col_count = len(rows[0].find_all(["th", "td"]))
            has_merged_cells = any(
                cell.get("colspan") not in (None, "1") or cell.get("rowspan") not in (None, "1")
                for cell in el.find_all(["td", "th"])
            )
            has_nested_table = el.find("table") is not None
            doc.tables.append(
                TableInfo(
                    index=table_idx,
                    has_header_row=has_header,
                    row_count=len(rows),
                    col_count=col_count,
                    preceding_heading=current_heading,
                    has_merged_cells=has_merged_cells,
                    has_nested_table=has_nested_table,
                )
            )
            table_idx += 1
            continue

        if name == "ac:structured-macro":
            doc.macro_count += 1
            continue

        if name in ("ac:image", "img"):
            alt = el.get("ac:alt") or el.get("alt") or ""
            filename_el = el.find(["ri:attachment", "ri:url"])
            filename = None
            if filename_el is not None:
                filename = filename_el.get("ri:filename") or filename_el.get("ri:value")
            elif name == "img":
                filename = el.get("src")
            doc.images.append(
                ImageInfo(
                    index=image_idx,
                    has_alt_text=bool(alt.strip()),
                    alt_text=alt,
                    filename=filename,
                    preceding_heading=current_heading,
                )
            )
            image_idx += 1
            continue

        if name in ("a", "ac:link"):
            href = el.get("href")
            doc.links.append(
                LinkInfo(
                    index=link_idx,
                    text=_link_text(el),
                    href=href,
                    preceding_heading=current_heading,
                )
            )
            link_idx += 1
            continue

        if name == "p" and not _has_ancestor(el, "table", "ac:structured-macro"):
            text = el.get_text(strip=True)
            if not text:
                continue
            doc.paragraphs.append(
                ParagraphInfo(
                    index=para_idx,
                    text=text,
                    word_count=len(text.split()),
                    preceding_heading=current_heading,
                )
            )
            para_idx += 1
            continue

    return doc
