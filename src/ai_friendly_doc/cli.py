"""CLI: Confluence 페이지/스페이스를 분석해 개선 제안 리포트를 만든다.

이 도구는 Confluence를 읽기만 하며, 어떤 경우에도 원본 문서를 수정하지 않는다.
"""

from __future__ import annotations

import argparse
import sys

from .analyzer import PageReport, analyze_page
from .config import ConfigError, load_confluence_config
from .confluence_client import ConfluenceClient
from .report import render_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-friendly-doc",
        description="Confluence 문서를 읽고 AI-friendly 관점의 개선 제안을 생성합니다.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--page-id",
        action="append",
        dest="page_ids",
        help="분석할 Confluence 페이지 ID (여러 번 지정 가능)",
    )
    target.add_argument(
        "--space-key",
        help="분석할 Confluence 스페이스 키 (스페이스 내 모든 현재 페이지를 분석)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="리포트를 저장할 파일 경로. 생략하면 표준출력에 출력",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_confluence_config()
    except ConfigError as e:
        print(f"설정 오류: {e}", file=sys.stderr)
        return 1

    client = ConfluenceClient(config)

    reports: list[PageReport] = []
    try:
        if args.page_ids:
            for page_id in args.page_ids:
                page = client.get_page(page_id)
                reports.append(analyze_page(page))
        else:
            for page in client.iter_space_pages(args.space_key):
                reports.append(analyze_page(page))
    except Exception as e:  # noqa: BLE001 - CLI 최상위 에러 처리
        print(f"Confluence 조회 중 오류: {e}", file=sys.stderr)
        return 1

    if not reports:
        print("분석할 페이지를 찾지 못했습니다.", file=sys.stderr)
        return 1

    output = render_report(reports)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"리포트 저장 완료: {args.output}")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
