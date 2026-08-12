import json
import os

import pytest

pytest.importorskip("fastapi")

# app.py는 import 시점에 SESSION_SECRET/CONFLUENCE_BASE_URL이 없으면 바로
# RuntimeError를 낸다(둘 다 필수 배포 설정). monkeypatch 픽스처는 아직 없는
# 시점(모듈 import 시점)이라 직접 세팅한다.
os.environ.setdefault("SESSION_SECRET", "test-secret-for-pytest")
os.environ.setdefault("CONFLUENCE_BASE_URL", "https://example.atlassian.net/wiki")

from ai_friendly_doc.analyzer import PageReport
from ai_friendly_doc.confluence_client import ConfluencePage
from ai_friendly_doc.guidelines import score_document
from ai_friendly_doc.web.app import (
    _build_email_subject,
    _decode_revisions,
    _encode_revisions,
    _render_copyable_revision_block,
)


def make_page_report(title: str, revised_document: str | None) -> PageReport:
    page = ConfluencePage(
        id="123",
        title=title,
        space_key="ENG",
        version=1,
        storage_html="<p>본문</p>",
        web_url="https://example.atlassian.net/wiki/spaces/ENG/pages/123",
    )
    return PageReport(
        page=page,
        suggestions=[],
        guideline_score=score_document([], llm_configured=False),
        original_document="원본 내용",
        revised_document=revised_document,
    )


# ---- 메일 제목 ----------------------------------------------------------


def test_email_subject_uses_original_document_title():
    reports = [make_page_report("비밀번호 정책", "# 수정본")]
    revisions = json.loads(_encode_revisions(reports))
    assert _build_email_subject(revisions) == "[AI Friendly 문서 개선 제안] 비밀번호 정책 수정 제안"


def test_email_subject_appends_count_suffix_for_multiple_pages():
    revisions = [{"title": "문서 A", "web_url": "", "revised_document": "# A"}, {"title": "문서 B"}]
    assert _build_email_subject(revisions) == "[AI Friendly 문서 개선 제안] 문서 A 수정 제안 외 1건"


def test_email_subject_falls_back_when_no_revisions():
    assert _build_email_subject([]) == "[AI Friendly 문서 개선 제안] 수정 제안"


# ---- revisions_json 인코딩/디코딩 (hidden 필드 round-trip) ----------------


def test_encode_decode_revisions_round_trip():
    reports = [make_page_report("문서 제목", "# 수정본 내용")]
    encoded = _encode_revisions(reports)
    decoded = _decode_revisions(encoded)
    assert decoded == [
        {
            "title": "문서 제목",
            "web_url": "https://example.atlassian.net/wiki/spaces/ENG/pages/123",
            "revised_document": "# 수정본 내용",
        }
    ]


def test_decode_revisions_returns_empty_list_for_invalid_json():
    assert _decode_revisions("") == []
    assert _decode_revisions("not json") == []
    assert _decode_revisions('{"not": "a list"}') == []


# ---- 이메일 맨 앞 "Confluence에 붙여넣기" 블록 ----------------------------


def test_copyable_revision_block_appears_before_rest_of_report_when_prepended():
    reports = [make_page_report("설치 가이드", "# 개선된 설치 가이드\n\n본문 내용")]
    revisions = _decode_revisions(_encode_revisions(reports))
    block = _render_copyable_revision_block(revisions)

    assert "Confluence에 바로 붙여넣기" in block
    assert "설치 가이드" in block
    # 렌더링된 서식이 아니라 복사용 소스(escape된 XHTML 텍스트)여야 한다.
    assert "&lt;h1&gt;" in block
    assert "<h1>" not in block  # 실제 <h1> 태그로 렌더링되면 안 된다(escape 필요)


def test_copyable_revision_block_empty_when_no_revised_document():
    reports = [make_page_report("실패한 페이지", None)]
    revisions = _decode_revisions(_encode_revisions(reports))
    assert _render_copyable_revision_block(revisions) == ""


def test_copyable_revision_block_skips_pages_without_revision_but_keeps_others():
    reports = [
        make_page_report("성공한 페이지", "# 수정본"),
        make_page_report("실패한 페이지", None),
    ]
    revisions = _decode_revisions(_encode_revisions(reports))
    block = _render_copyable_revision_block(revisions)
    assert "성공한 페이지" in block
    assert "실패한 페이지" not in block
