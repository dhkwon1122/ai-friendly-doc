"""제안 목록을 사람이 읽기 좋은 Markdown 리포트로 변환한다."""

from __future__ import annotations

from .analyzer import PageReport
from .guidelines import GuidelineComplianceReport
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


def _render_guideline_checklist(
    compliance: GuidelineComplianceReport, revision_compliance: GuidelineComplianceReport | None
) -> list[str]:
    lines = ["**핵심 가이드라인 준수**", ""]
    if revision_compliance is not None:
        # 최종 수정본이 검증까지 된 경우에만 "수정본 상태" 컬럼을 옆에
        # 추가한다 - 원본과 수정본의 준수 여부를 한 표에서 바로 비교할
        # 수 있게 한다.
        revision_by_id = {r.guideline.id: r for r in revision_compliance.results}
        lines.append("| 가이드라인 | 원본 상태 | 수정본 상태 |")
        lines.append("| --- | --- | --- |")
        for result in compliance.results:
            revision_result = revision_by_id.get(result.guideline.id)
            revision_label = STATUS_LABEL[revision_result.status] if revision_result else "-"
            lines.append(f"| {result.guideline.label} | {STATUS_LABEL[result.status]} | {revision_label} |")
    else:
        lines.append("| 가이드라인 | 상태 |")
        lines.append("| --- | --- |")
        for result in compliance.results:
            lines.append(f"| {result.guideline.label} | {STATUS_LABEL[result.status]} |")
    lines.append("")
    return lines


def render_page_section(report: PageReport) -> str:
    page = report.page
    lines = [f"## {page.title}"]
    if page.web_url:
        # 마크다운 링크 문법으로 써야 렌더링됐을 때 실제로 클릭 가능한
        # 링크가 된다 (원본 URL을 그냥 텍스트로 두면 안 눌린다).
        lines.append(f"- 원본: [{page.web_url}]({page.web_url})")
    lines.append(f"- 페이지 ID: {page.id} / 스페이스: {page.space_key} / 버전: {page.version}")
    lines.append("")
    # 가장 궁금해하는 결과물(수정 제안)을 발견 사항 나열보다 먼저 보여준다.
    lines.extend(_render_revision_section(report))
    lines.extend(_render_guideline_checklist(report.guideline_compliance, report.revision_guideline_compliance))

    if not report.suggestions:
        lines.append("발견된 제안 사항 없음.")
        lines.append("")
    else:
        ordered = sorted(report.suggestions, key=lambda s: SEVERITY_ORDER[s.severity])
        for s in ordered:
            lines.append(f"### [{SEVERITY_LABEL[s.severity]}] {s.location}")
            lines.append(f"- 규칙: `{s.rule_id}`")
            lines.append(f"- 문제: {s.message}")
            lines.append(f"- 제안: {s.suggestion}")
            lines.append("")

    return "\n".join(lines)


def _render_revision_section(report: PageReport) -> list[str]:
    lines = ["**최종 수정본**", ""]
    if report.revised_document:
        lines.append("```")
        lines.append(report.revised_document)
        lines.append("```")
    else:
        lines.append("(LLM이 설정되어 있지 않거나 수정본 생성에 실패해 만들어지지 않았습니다.)")
    lines.append("")
    return lines


def render_summary_table(reports: list[PageReport]) -> str:
    lines = [
        "| 페이지 | 제안 수 | 심각 | 경고 | 참고 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in reports:
        counts = {Severity.CRITICAL: 0, Severity.WARNING: 0, Severity.INFO: 0}
        for s in r.suggestions:
            counts[s.severity] += 1
        lines.append(
            f"| {r.page.title} | {len(r.suggestions)} | {counts[Severity.CRITICAL]} "
            f"| {counts[Severity.WARNING]} | {counts[Severity.INFO]} |"
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
