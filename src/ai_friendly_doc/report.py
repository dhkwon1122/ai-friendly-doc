"""제안 목록을 사람이 읽기 좋은 Markdown 리포트로 변환한다."""

from __future__ import annotations

from .analyzer import PageReport
from .guidelines import ScoreReport
from .rules import Severity

SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
SEVERITY_LABEL = {
    Severity.CRITICAL: "🔴 심각",
    Severity.WARNING: "🟡 경고",
    Severity.INFO: "🔵 참고",
}
STATUS_LABEL = {
    "compliant": "✅ 준수",
    "violated": "⚠️ 위반",
    "unverifiable": "❔ 확인 불가",
}


def _render_guideline_checklist(score: ScoreReport) -> list[str]:
    lines = ["**핵심 가이드라인 준수**", ""]
    if score.score is not None:
        lines.append(f"점수: **{score.score}점** ({score.compliant_count}/{score.checked_count}개 항목 준수)")
    else:
        lines.append("점수: 계산 불가 (확인 가능한 항목이 없음 - LLM 미설정)")
    lines.append("")
    lines.append("| 가이드라인 | 상태 |")
    lines.append("| --- | --- |")
    for result in score.results:
        lines.append(f"| {result.guideline.label} | {STATUS_LABEL[result.status]} |")
    lines.append("")
    return lines


def render_page_section(report: PageReport) -> str:
    page = report.page
    lines = [f"## {page.title}"]
    if page.web_url:
        lines.append(f"- 원본: {page.web_url}")
    lines.append(f"- 페이지 ID: {page.id} / 스페이스: {page.space_key} / 버전: {page.version}")
    lines.append("")
    lines.extend(_render_guideline_checklist(report.guideline_score))

    if not report.suggestions:
        lines.append("발견된 제안 사항 없음.")
        lines.append("")
        return "\n".join(lines)

    ordered = sorted(report.suggestions, key=lambda s: SEVERITY_ORDER[s.severity])
    for s in ordered:
        lines.append(f"### [{SEVERITY_LABEL[s.severity]}] {s.location}")
        lines.append(f"- 규칙: `{s.rule_id}`")
        lines.append(f"- 문제: {s.message}")
        lines.append(f"- 제안: {s.suggestion}")
        lines.append("")

    return "\n".join(lines)


def render_summary_table(reports: list[PageReport]) -> str:
    lines = [
        "| 페이지 | 제안 수 | 심각 | 경고 | 참고 | 핵심 가이드 점수 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in reports:
        counts = {Severity.CRITICAL: 0, Severity.WARNING: 0, Severity.INFO: 0}
        for s in r.suggestions:
            counts[s.severity] += 1
        score = r.guideline_score.score
        score_text = f"{score}점" if score is not None else "-"
        lines.append(
            f"| {r.page.title} | {len(r.suggestions)} | {counts[Severity.CRITICAL]} "
            f"| {counts[Severity.WARNING]} | {counts[Severity.INFO]} | {score_text} |"
        )
    return "\n".join(lines)


def render_report(reports: list[PageReport]) -> str:
    parts = ["# AI-Friendly 문서 개선 제안 리포트", ""]
    parts.append(f"총 {len(reports)}개 페이지 분석, 총 {sum(len(r.suggestions) for r in reports)}건 제안")
    parts.append("")
    parts.append(render_summary_table(reports))
    parts.append("")
    parts.append("---")
    parts.append("")
    for r in reports:
        parts.append(render_page_section(r))
        parts.append("---")
        parts.append("")
    return "\n".join(parts)
