"""구조적 개선 제안을 위한 스타터 규칙 모음.

실제 조직에서 쓸 규칙 세트는 추후 별도로 정리될 예정이며, 여기 있는 규칙들은
Rule 엔진이 어떻게 동작하는지 보여주는 기본 예시다. 필요에 맞게 자유롭게
추가/수정/삭제하면 된다.
"""

from __future__ import annotations

from ..parser import ParsedDoc
from .base import Rule, Severity, Suggestion

AMBIGUOUS_LINK_TEXTS = {
    "여기",
    "여기를 클릭",
    "여기 클릭",
    "클릭",
    "바로가기",
    "링크",
    "click here",
    "here",
    "this link",
    "link",
}

LONG_PARAGRAPH_WORD_THRESHOLD = 120


class HeadingHierarchySkipRule(Rule):
    id = "heading-hierarchy-skip"
    description = "제목 레벨이 한 단계 이상 건너뛰는 경우를 찾는다 (예: H1 다음 바로 H3)."

    def check(self, doc: ParsedDoc) -> list[Suggestion]:
        suggestions: list[Suggestion] = []
        prev_level: int | None = None
        for heading in doc.headings:
            if prev_level is not None and heading.level - prev_level > 1:
                suggestions.append(
                    Suggestion(
                        rule_id=self.id,
                        severity=Severity.WARNING,
                        location=f"제목 '{heading.text}' (H{heading.level})",
                        message=(
                            f"이전 제목이 H{prev_level}인데 바로 H{heading.level}로 건너뛰어 "
                            "문서 구조를 파싱하는 AI/도구가 계층을 오해할 수 있음"
                        ),
                        suggestion=f"H{prev_level + 1} 제목을 추가하거나 이 제목을 H{prev_level + 1}로 낮추세요.",
                    )
                )
            prev_level = heading.level
        return suggestions


class MissingH1Rule(Rule):
    id = "missing-h1"
    description = "문서에 최상위 제목(H1)이 하나도 없는 경우를 찾는다."

    def check(self, doc: ParsedDoc) -> list[Suggestion]:
        if doc.headings and not any(h.level == 1 for h in doc.headings):
            return [
                Suggestion(
                    rule_id=self.id,
                    severity=Severity.INFO,
                    location="문서 전체",
                    message="H1 제목이 없어 문서의 최상위 주제를 구조적으로 파악하기 어려움",
                    suggestion="문서 최상단에 문서 전체를 대표하는 H1 제목을 추가하세요.",
                )
            ]
        return []


class MissingTableHeaderRule(Rule):
    id = "missing-table-header"
    description = "헤더 행(th)이 없는 표를 찾는다."

    def check(self, doc: ParsedDoc) -> list[Suggestion]:
        suggestions = []
        for table in doc.tables:
            if not table.has_header_row and table.row_count > 0:
                section = f"'{table.preceding_heading}' 섹션의 " if table.preceding_heading else ""
                suggestions.append(
                    Suggestion(
                        rule_id=self.id,
                        severity=Severity.WARNING,
                        location=f"{section}표 #{table.index + 1} ({table.row_count}행 x {table.col_count}열)",
                        message="표에 헤더 행이 없어 각 열이 무엇을 의미하는지 문맥 없이는 알기 어려움",
                        suggestion="첫 번째 행을 헤더(th)로 지정해 각 열의 의미를 명시하세요.",
                    )
                )
        return suggestions


class MissingAltTextRule(Rule):
    id = "missing-alt-text"
    description = "대체 텍스트(alt)가 없는 이미지를 찾는다."

    def check(self, doc: ParsedDoc) -> list[Suggestion]:
        suggestions = []
        for image in doc.images:
            if not image.has_alt_text:
                section = f"'{image.preceding_heading}' 섹션의 " if image.preceding_heading else ""
                name = f" ({image.filename})" if image.filename else ""
                suggestions.append(
                    Suggestion(
                        rule_id=self.id,
                        severity=Severity.WARNING,
                        location=f"{section}이미지 #{image.index + 1}{name}",
                        message="대체 텍스트가 없어 이미지 내용을 텍스트 기반으로 이해할 수 없음",
                        suggestion="이미지가 전달하는 핵심 정보를 요약한 alt 텍스트를 추가하세요.",
                    )
                )
        return suggestions


class AmbiguousLinkTextRule(Rule):
    id = "ambiguous-link-text"
    description = "'여기', 'click here'처럼 문맥 없이는 의미를 알 수 없는 링크 텍스트를 찾는다."

    def check(self, doc: ParsedDoc) -> list[Suggestion]:
        suggestions = []
        for link in doc.links:
            normalized = link.text.strip().lower()
            if normalized in AMBIGUOUS_LINK_TEXTS:
                section = f"'{link.preceding_heading}' 섹션의 " if link.preceding_heading else ""
                suggestions.append(
                    Suggestion(
                        rule_id=self.id,
                        severity=Severity.INFO,
                        location=f"{section}링크 #{link.index + 1} (텍스트: '{link.text}')",
                        message="링크 텍스트만으로는 어디로 연결되는지 알 수 없어, 링크만 추출해 보는 AI/도구가 맥락을 잃음",
                        suggestion="링크 대상을 설명하는 구체적인 텍스트로 바꾸세요 (예: '배포 가이드 문서').",
                    )
                )
        return suggestions


class LongParagraphRule(Rule):
    id = "long-paragraph"
    description = f"단어 수가 {LONG_PARAGRAPH_WORD_THRESHOLD}개를 넘는, 지나치게 긴 문단을 찾는다."

    def check(self, doc: ParsedDoc) -> list[Suggestion]:
        suggestions = []
        for para in doc.paragraphs:
            if para.word_count > LONG_PARAGRAPH_WORD_THRESHOLD:
                section = f"'{para.preceding_heading}' 섹션의 " if para.preceding_heading else ""
                preview = para.text[:40] + ("..." if len(para.text) > 40 else "")
                suggestions.append(
                    Suggestion(
                        rule_id=self.id,
                        severity=Severity.INFO,
                        location=f"{section}문단 #{para.index + 1} (약 {para.word_count}단어, '{preview}')",
                        message="한 문단이 지나치게 길어 요약/청크 분할 시 하나의 의미 단위로 다루기 어려움",
                        suggestion="소제목이나 목록을 활용해 여러 문단/섹션으로 나누세요.",
                    )
                )
        return suggestions
