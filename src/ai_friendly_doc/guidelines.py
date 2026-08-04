"""AI-friendly 문서 작성 가이드라인 정의와, 그 준수 여부로 문서를 점수화하는 로직.

핵심 가이드라인(core) 7개 + 추가 권장 가이드(extra) 7개로 구성된다. 점수는
핵심 가이드라인만 대상으로 한다 (추가 권장 가이드는 리포트에 항목으로는
나오지만 점수에는 반영하지 않음).

각 가이드라인은 규칙 엔진(rules/starter.py)의 결정론적 체크나 LLM 검토
(llm_review.py)가 만드는 Suggestion.guideline_id로 연결된다. llm_only=True인
가이드라인은 결정론적으로 판별할 방법이 없어 LLM 검토가 설정돼 있을 때만
확인 가능하다 - LLM이 꺼져 있으면 "확인 불가"로 표시하고 점수 계산에서
제외한다 (지키지 않은 것으로 간주하지 않음).
"""

from __future__ import annotations

from dataclasses import dataclass

from .rules import Suggestion


@dataclass(frozen=True)
class Guideline:
    id: str
    tier: str  # "core" | "extra"
    label: str
    llm_only: bool  # 결정론적 규칙이 없어 LLM 검토에만 의존하는지


GUIDELINES: list[Guideline] = [
    Guideline("core-1", "core", "대명사 사용 자제 및 주어 포함", llm_only=True),
    Guideline("core-2", "core", "이미지/표 설명 표기", llm_only=False),
    Guideline("core-3", "core", "원본/참조 문서 경로 표기", llm_only=True),
    Guideline("core-4", "core", "사용 용어 통일", llm_only=True),
    Guideline("core-5", "core", "전문 용어 별도 정리", llm_only=True),
    Guideline("core-6", "core", "상대적 시간 표현 대신 절대 날짜 명시", llm_only=False),
    Guideline("core-7", "core", "문서의 자체 완결성 (참조 문서 없이도 핵심 맥락 파악 가능)", llm_only=True),
    Guideline("extra-1", "extra", "서론/본론/결론 흐름으로 작성", llm_only=True),
    Guideline("extra-2", "extra", "셀 병합/표 중첩 지양", llm_only=False),
    Guideline("extra-3", "extra", "스타일 기능 사용 (일반 텍스트로 제목/강조 흉내내지 않기)", llm_only=True),
    Guideline("extra-4", "extra", "주제가 바뀔 때 섹션 분리", llm_only=False),
    Guideline("extra-5", "extra", "제목만 봐도 내용 파악 가능하게 작성", llm_only=False),
    Guideline("extra-6", "extra", "절차성 내용은 번호 리스트로 작성", llm_only=False),
    Guideline("extra-7", "extra", "과도한 매크로/위젯보다 기본 텍스트·표 구조 우선", llm_only=False),
]

GUIDELINES_BY_ID: dict[str, Guideline] = {g.id: g for g in GUIDELINES}
CORE_GUIDELINES: list[Guideline] = [g for g in GUIDELINES if g.tier == "core"]
EXTRA_GUIDELINES: list[Guideline] = [g for g in GUIDELINES if g.tier == "extra"]


@dataclass(frozen=True)
class GuidelineResult:
    guideline: Guideline
    status: str  # "compliant" | "violated" | "unverifiable"
    violation_count: int


@dataclass(frozen=True)
class ScoreReport:
    results: list[GuidelineResult]  # 핵심 가이드라인 7개 전부, 상태 무관하게 포함
    checked_count: int  # "unverifiable"을 제외한 항목 수
    compliant_count: int
    score: int | None  # 0~100. checked_count가 0이면 계산 불가(None)


def score_document(suggestions: list[Suggestion], llm_configured: bool) -> ScoreReport:
    violation_counts: dict[str, int] = {}
    for s in suggestions:
        if s.guideline_id:
            violation_counts[s.guideline_id] = violation_counts.get(s.guideline_id, 0) + 1

    results: list[GuidelineResult] = []
    for guideline in CORE_GUIDELINES:
        count = violation_counts.get(guideline.id, 0)
        if count > 0:
            status = "violated"
        elif guideline.llm_only and not llm_configured:
            status = "unverifiable"
        else:
            status = "compliant"
        results.append(GuidelineResult(guideline=guideline, status=status, violation_count=count))

    checked = [r for r in results if r.status != "unverifiable"]
    compliant = [r for r in checked if r.status == "compliant"]
    score = round(100 * len(compliant) / len(checked)) if checked else None

    return ScoreReport(
        results=results,
        checked_count=len(checked),
        compliant_count=len(compliant),
        score=score,
    )
