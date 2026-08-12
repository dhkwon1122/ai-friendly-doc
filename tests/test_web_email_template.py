import html
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
from ai_friendly_doc.guidelines import check_guideline_compliance
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
        guideline_compliance=check_guideline_compliance([], llm_configured=False),
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
    # 렌더링된 서식이 아니라 복사용 소스(escape된 매크로 XML 텍스트)여야
    # 한다 - 마크다운을 우리가 직접 변환하지 않고 원문 그대로 Markdown
    # 매크로에 감싼다.
    assert "&lt;ac:structured-macro ac:name=&quot;markdown&quot;" in block
    assert "<ac:structured-macro" not in block  # 실제 태그로 렌더링되면 안 된다(escape 필요)
    assert "# 개선된 설치 가이드" in block  # 원문 마크다운이 변환 없이 그대로 담겨야 한다


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


def test_copyable_revision_block_tells_user_to_reuse_original_title():
    # 페이지 제목은 원본 문서 제목을 그대로 쓰면 되므로, 별도로 다른 제목을
    # 제안하지 않고 "원본 문서 제목을 그대로 입력"하라고 안내해야 한다.
    reports = [make_page_report("비밀번호 정책", "# 수정본")]
    revisions = _decode_revisions(_encode_revisions(reports))
    block = _render_copyable_revision_block(revisions)

    assert "원본 문서 제목을 그대로 입력" in block
    assert "AI 개선 제안" not in block  # 예전의 "{제목} (AI 개선 제안)" 식 제안 제목은 더 안 보여준다
    assert "제안 제목" not in block


def test_copyable_revision_block_content_starts_right_after_original_link():
    # 복사용 소스(매크로 본문) 안에서 원본 문서 링크 줄 바로 아래(빈 줄 하나
    # 두고)에 수정본 내용이 이어져야 한다 - 사이에 다른 안내문이 끼어들면
    # 안 된다.
    reports = [make_page_report("비밀번호 정책", "# 수정본 제목\n\n본문")]
    revisions = _decode_revisions(_encode_revisions(reports))
    block = _render_copyable_revision_block(revisions)

    pre_start = block.index("<pre")
    pre_end = block.index("</pre>")
    pre_content = html.unescape(block[pre_start:pre_end])

    cdata_start = pre_content.index("<![CDATA[") + len("<![CDATA[")
    cdata_end = pre_content.index("]]>", cdata_start)
    macro_body = pre_content[cdata_start:cdata_end]

    assert macro_body.startswith("*원본 문서:")
    rest = macro_body.split("\n\n", 1)[1]
    assert rest.startswith("# 수정본 제목")


def test_copyable_revision_block_includes_original_link_inside_copyable_source():
    # 원본 문서 링크는 반대로 붙여넣었을 때 실제 페이지 본문에 남아있어야
    # 의미가 있으므로, <pre> 블록(복사용 소스, 즉 매크로 본문) 안에 마크다운
    # 링크 문법으로 포함돼야 한다.
    reports = [make_page_report("비밀번호 정책", "# 수정본")]
    revisions = _decode_revisions(_encode_revisions(reports))
    block = _render_copyable_revision_block(revisions)

    pre_start = block.index("<pre")
    pre_end = block.index("</pre>")
    pre_content = html.unescape(block[pre_start:pre_end])

    assert "원본 문서" in pre_content
    assert "https://example.atlassian.net/wiki/spaces/ENG/pages/123" in pre_content
    # 마크다운 링크 문법 [제목](url)로 들어가 있어야 한다(Confluence의
    # 마크다운 매크로가 렌더링 시 실제 링크로 바꿔준다).
    assert "[비밀번호 정책](https://example.atlassian.net/wiki/spaces/ENG/pages/123)" in pre_content


def test_copyable_revision_block_omits_link_when_web_url_missing():
    revisions = [{"title": "링크 없는 페이지", "web_url": "", "revised_document": "# 수정본"}]
    block = _render_copyable_revision_block(revisions)

    # 안내 문구에는 "원본 문서 제목을 그대로 입력"처럼 일반적인 문구가
    # 나오지만, web_url이 없으면 복사용 소스(<pre> 안)에는 원본 문서 링크
    # 문단 자체가 들어가면 안 된다.
    pre_start = block.index("<pre")
    pre_end = block.index("</pre>")
    pre_content = block[pre_start:pre_end]
    assert "원본 문서" not in pre_content
