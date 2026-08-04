"""구조적 개선 제안을 위한 스타터 규칙 모음.

여기 있는 규칙들은 guidelines.py에 정의된 "AI-friendly 문서 작성 가이드라인"
중 결정론적으로(코드로) 판별 가능한 항목들을 구현한다. 각 Suggestion의
guideline_id가 어떤 가이드라인에 대응하는지를 나타낸다. 결정론적으로 판별하기
어려운 가이드라인(대명사/주어 생략, 용어 통일, 문서 자체 완결성 등)은
llm_review.py가 LLM으로 대신 확인한다.
"""

from __future__ import annotations

import re

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

RELATIVE_TIME_EXPRESSIONS = [
    "최근",
    "지난주",
    "지난달",
    "지난해",
    "이번 주",
    "이번주",
    "이번 달",
    "이번달",
    "다음 주",
    "다음주",
    "다음 달",
    "다음달",
    "머지않아",
    "얼마 전",
    "요즘",
    "당분간",
    "조만간",
]

VAGUE_HEADINGS = {
    "설정",
    "기타",
    "참고",
    "개요",
    "소개",
    "정보",
    "내용",
    "안내",
    "참조",
    "etc",
    "misc",
    "info",
    "note",
}

MACRO_COUNT_THRESHOLD = 8

_INLINE_NUMBER_PATTERN = re.compile(r"(?:^|\s)([1-9][0-9]?[).]|첫째|둘째|셋째|넷째|다섯째)")


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
                        guideline_id="extra-4",
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
                    guideline_id="extra-4",
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
                        guideline_id="core-2",
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
                        guideline_id="core-2",
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
                        guideline_id="core-1",
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


class RelativeTimeExpressionRule(Rule):
    id = "relative-time-expression"
    description = "'최근', '지난주'처럼 시간이 지나면 틀리게 되는 상대적 시간 표현을 찾는다."

    def check(self, doc: ParsedDoc) -> list[Suggestion]:
        suggestions = []
        for para in doc.paragraphs:
            found = [kw for kw in RELATIVE_TIME_EXPRESSIONS if kw in para.text]
            if found:
                section = f"'{para.preceding_heading}' 섹션의 " if para.preceding_heading else ""
                preview = para.text[:40] + ("..." if len(para.text) > 40 else "")
                suggestions.append(
                    Suggestion(
                        rule_id=self.id,
                        severity=Severity.INFO,
                        location=f"{section}문단 #{para.index + 1} ('{preview}')",
                        message=f"상대적 시간 표현({', '.join(found)})은 문서가 오래되면 틀린 정보가 됨",
                        suggestion="구체적인 날짜(예: '2024년 3월')로 바꾸거나 문서 최종 수정일을 명시하세요.",
                        guideline_id="core-6",
                    )
                )
        return suggestions


class MergedOrNestedTableRule(Rule):
    id = "merged-or-nested-table"
    description = "셀 병합(colspan/rowspan)이나 표 안에 표가 중첩된 경우를 찾는다."

    def check(self, doc: ParsedDoc) -> list[Suggestion]:
        suggestions = []
        for table in doc.tables:
            problems = []
            if table.has_merged_cells:
                problems.append("셀 병합(colspan/rowspan)")
            if table.has_nested_table:
                problems.append("표 중첩")
            if not problems:
                continue
            section = f"'{table.preceding_heading}' 섹션의 " if table.preceding_heading else ""
            suggestions.append(
                Suggestion(
                    rule_id=self.id,
                    severity=Severity.INFO,
                    location=f"{section}표 #{table.index + 1}",
                    message=f"{', '.join(problems)}이 있어 표를 순차적으로 읽는 AI/도구가 셀 관계를 오해하기 쉬움",
                    suggestion="병합된 셀은 값을 각 행/열에 반복 기입하고, 중첩된 표는 별도 표나 목록으로 분리하세요.",
                    guideline_id="extra-2",
                )
            )
        return suggestions


class VagueHeadingRule(Rule):
    id = "vague-heading"
    description = "'설정', '기타'처럼 그 자체만으로는 내용을 짐작하기 어려운 제목을 찾는다."

    def check(self, doc: ParsedDoc) -> list[Suggestion]:
        suggestions = []
        for heading in doc.headings:
            normalized = heading.text.strip().lower()
            if normalized in VAGUE_HEADINGS:
                suggestions.append(
                    Suggestion(
                        rule_id=self.id,
                        severity=Severity.INFO,
                        location=f"제목 '{heading.text}' (H{heading.level})",
                        message="제목만으로는 이 섹션이 어떤 내용을 다루는지 짐작하기 어려움",
                        suggestion="무엇에 대한 내용인지 구체적으로 드러나는 제목으로 바꾸세요 (예: 'Redis 캐시 설정').",
                        guideline_id="extra-5",
                    )
                )
        return suggestions


class PseudoNumberedListRule(Rule):
    id = "pseudo-numbered-list"
    description = "번호 매기기 목록으로 써야 할 절차를 하나의 문단 안에 나열한 경우를 찾는다."

    def check(self, doc: ParsedDoc) -> list[Suggestion]:
        suggestions = []
        for para in doc.paragraphs:
            matches = _INLINE_NUMBER_PATTERN.findall(para.text)
            if len(matches) >= 2:
                section = f"'{para.preceding_heading}' 섹션의 " if para.preceding_heading else ""
                preview = para.text[:40] + ("..." if len(para.text) > 40 else "")
                suggestions.append(
                    Suggestion(
                        rule_id=self.id,
                        severity=Severity.INFO,
                        location=f"{section}문단 #{para.index + 1} ('{preview}')",
                        message="순서가 있는 절차를 문단 안에 번호만 매겨 나열하고 있어 AI가 단계를 놓치기 쉬움",
                        suggestion="번호 매기기 목록(순서 있는 리스트)으로 바꾸세요.",
                        guideline_id="extra-6",
                    )
                )
        return suggestions


class ExcessiveMacroRule(Rule):
    id = "excessive-macros"
    description = f"페이지에 Confluence 매크로가 {MACRO_COUNT_THRESHOLD}개를 넘게 쓰인 경우를 찾는다."

    def check(self, doc: ParsedDoc) -> list[Suggestion]:
        if doc.macro_count > MACRO_COUNT_THRESHOLD:
            return [
                Suggestion(
                    rule_id=self.id,
                    severity=Severity.INFO,
                    location="문서 전체",
                    message=(
                        f"매크로가 {doc.macro_count}개나 사용되어, 매크로를 렌더링하지 못하는 "
                        "AI/도구는 문서 구조 상당 부분을 놓칠 수 있음"
                    ),
                    suggestion="가능하면 복잡한 매크로 대신 기본 텍스트/표/목록 구조로 대체하세요.",
                    guideline_id="extra-7",
                )
            ]
        return []
