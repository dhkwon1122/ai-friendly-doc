"""웹 UI: 사용자가 로그인해서 본인 Confluence 토큰을 저장하고,
페이지/스페이스를 분석해 개선 제안 리포트를 브라우저에서 바로 확인할 수 있게 한다.
"""

from __future__ import annotations

import html as html_module
import json
import os
from pathlib import Path

import markdown as md
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from ..analyzer import PageReport, analyze_page, analyze_page_findings, generate_page_revision
from ..config import DEFAULT_WEB_BASE_URL, ConfluenceConfig, parse_bool_env
from ..confluence_client import ConfluenceClient
from ..confluence_markdown_macro import escape_markdown_link_text, markdown_to_confluence_markdown_macro
from ..guidelines import CORE_GUIDELINES, EXTRA_GUIDELINES, score_document
from ..llm_review import storage_html_to_plain_text
from ..report import render_report
from ..rules import Severity, Suggestion
from . import db
from .mailer import MailConfigError, send_report_email
from .security import SecurityConfigError, decrypt_token, encrypt_token, hash_password, verify_password

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="ai-friendly-doc")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

session_secret = os.environ.get("SESSION_SECRET")
if not session_secret:
    raise RuntimeError(
        "SESSION_SECRET 환경변수가 설정되지 않았습니다. "
        "무작위 문자열을 생성해 .env에 추가하세요 (예: python -c \"import secrets; print(secrets.token_hex(32))\")"
    )
app.add_middleware(SessionMiddleware, secret_key=session_secret, https_only=False)


def _fixed_base_url() -> str:
    """조직 전체가 공유하는 배포 단위 설정. 여러 Confluence 인스턴스가 섞여
    저장되는 걸 막고(다른 앱과 confluence_credentials 테이블을 공유하기도
    쉽도록) 사용자가 직접 입력하지 않고 .env의 CONFLUENCE_BASE_URL을 그대로
    쓴다 - 그래서 웹 UI에서는 필수 설정이다."""
    value = (os.environ.get("CONFLUENCE_BASE_URL") or "").strip().rstrip("/")
    if not value:
        raise RuntimeError(
            "CONFLUENCE_BASE_URL 환경변수가 설정되지 않았습니다. 웹 UI는 사용자가 "
            "Base URL을 직접 입력하지 않으므로 .env에서 반드시 지정해야 합니다."
        )
    return value


_fixed_base_url()  # 필수 설정이 빠졌으면 요청을 받기 전에(기동 시점에) 바로 실패시킨다.


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


def current_user(request: Request) -> db.User | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    return db.get_user_by_id(user_id)


def render(request: Request, template: str, **context) -> HTMLResponse:
    context.setdefault("user", current_user(request))
    return templates.TemplateResponse(request, template, context)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if current_user(request):
        return RedirectResponse("/analyze", status_code=303)
    return RedirectResponse("/login", status_code=303)


# ---- 인증 ----------------------------------------------------------------


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return render(request, "register.html")


@app.post("/register", response_class=HTMLResponse)
def register_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    if not username or not password:
        return render(request, "register.html", error="아이디와 비밀번호를 모두 입력하세요.")
    if len(password) < 8:
        return render(request, "register.html", error="비밀번호는 8자 이상이어야 합니다.")
    if db.get_user_by_username(username):
        return render(request, "register.html", error="이미 사용 중인 아이디입니다.")

    user = db.create_user(username, hash_password(password))
    request.session["user_id"] = user.id
    return RedirectResponse("/settings", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return render(request, "login.html")


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = db.get_user_by_username(username.strip())
    if not user or not verify_password(password, user.password_hash):
        return render(request, "login.html", error="아이디 또는 비밀번호가 올바르지 않습니다.")
    request.session["user_id"] = user.id
    return RedirectResponse("/analyze", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---- Confluence 연동 정보 설정 ---------------------------------------------


def _verify_ssl() -> bool:
    """사내 Confluence가 자체 서명 인증서를 쓰면 .env에 CONFLUENCE_VERIFY_SSL=false로
    끌 수 있다. base_url과 마찬가지로 서버 전체에 적용되는 배포 단위 설정이다."""
    return parse_bool_env(os.environ.get("CONFLUENCE_VERIFY_SSL"), default=True)


def _web_base_url() -> str:
    """리포트/이메일에 넣는 "원본 문서 링크"용 base URL. REST API 호출에
    쓰는 CONFLUENCE_BASE_URL과 별개다(API 게이트웨이 주소와 사람이
    브라우저로 보는 주소가 다른 환경이 흔함). 지정 안 하면 조직 기본값을
    쓴다."""
    return (os.environ.get("CONFLUENCE_WEB_BASE_URL") or DEFAULT_WEB_BASE_URL).rstrip("/")


@app.get("/settings", response_class=HTMLResponse)
def settings_form(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    creds = db.get_credentials(user.id)
    onboarding = request.query_params.get("onboarding") == "1"
    return render(
        request,
        "settings.html",
        creds=creds,
        onboarding=onboarding,
        fixed_base_url=_fixed_base_url(),
    )


@app.post("/settings", response_class=HTMLResponse)
def settings_submit(
    request: Request,
    api_token: str = Form(""),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    fixed_base_url = _fixed_base_url()
    existing = db.get_credentials(user.id)

    if not api_token and not existing:
        return render(
            request,
            "settings.html",
            creds=existing,
            error="Personal Access Token(PAT)을 입력하세요.",
            fixed_base_url=fixed_base_url,
        )

    try:
        token_to_store = encrypt_token(api_token) if api_token else existing.encrypted_token
    except SecurityConfigError as e:
        return render(request, "settings.html", creds=existing, error=str(e), fixed_base_url=fixed_base_url)

    db.save_credentials(
        user_id=user.id,
        base_url=fixed_base_url,
        # 계정 ID/비밀번호(Basic Auth)는 지원하지 않고 PAT(Bearer) 인증만
        # 쓰므로 값은 항상 고정. DB 컬럼 자체는 스키마 변경(마이그레이션) 없이
        # 그대로 둔다.
        auth_type="bearer",
        email=None,
        encrypted_token=token_to_store,
    )
    return render(
        request,
        "settings.html",
        creds=db.get_credentials(user.id),
        saved=True,
        fixed_base_url=fixed_base_url,
    )


# ---- 분석 ------------------------------------------------------------------


def _build_client(user: db.User) -> ConfluenceClient:
    creds = db.get_credentials(user.id)
    if not creds:
        raise SecurityConfigError("먼저 설정 페이지에서 Confluence 연동 정보를 입력하세요.")
    config = ConfluenceConfig(
        base_url=_fixed_base_url(),
        api_token=decrypt_token(creds.encrypted_token),
        verify_ssl=_verify_ssl(),
        web_base_url=_web_base_url(),
    )
    return ConfluenceClient(config)


def _fetch_pages(user: db.User, mode: str, value: str):
    client = _build_client(user)
    if mode == "page_ids":
        page_ids = [p.strip() for p in value.replace(",", "\n").splitlines() if p.strip()]
        return [client.get_page(page_id) for page_id in page_ids]
    return list(client.iter_space_pages(value.strip()))


def _run_analysis(user: db.User, mode: str, value: str):
    """조회 + AI 분석 + 최종 수정본까지 한 번에 (다운로드/이메일을 mode/value만
    으로 직접 호출하는 경우의 하위 호환 경로에서만 쓴다 - 화면 흐름은 이제
    findings와 revision을 독립된 버튼/요청으로 나눴다)."""
    return [analyze_page(page) for page in _fetch_pages(user, mode, value)]


def _run_findings_analysis(user: db.User, mode: str, value: str):
    """"AI 분석" 버튼 - 규칙 검사 + LLM 찾기/수정안만 수행하고 최종 수정본은
    만들지 않는다 (가장 자주 실패하는 부분이라 별도 버튼으로 분리)."""
    return [analyze_page_findings(page) for page in _fetch_pages(user, mode, value)]


def _encode_suggestions_by_page(reports: list[PageReport]) -> str:
    """PageReport 목록의 suggestions를 {page_id: [suggestion dict, ...]}
    JSON으로 직렬화한다. "최종 수정본 제안" 버튼을 누를 때 AI 분석에서 이미
    찾은 문제들을 이어서 참고할 수 있도록 화면에 hidden 필드로 실어 보낸다."""
    data = {
        r.page.id: [
            {
                "rule_id": s.rule_id,
                "severity": s.severity.value,
                "location": s.location,
                "message": s.message,
                "suggestion": s.suggestion,
                "guideline_id": s.guideline_id,
            }
            for s in r.suggestions
        ]
        for r in reports
    }
    return json.dumps(data, ensure_ascii=False)


def _decode_suggestions_by_page(suggestions_json: str) -> dict[str, list[Suggestion]]:
    if not suggestions_json:
        return {}
    try:
        raw = json.loads(suggestions_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    result: dict[str, list[Suggestion]] = {}
    for page_id, items in raw.items():
        if not isinstance(items, list):
            continue
        suggestions = []
        for item in items:
            try:
                suggestions.append(
                    Suggestion(
                        rule_id=str(item["rule_id"]),
                        severity=Severity(item["severity"]),
                        location=str(item["location"]),
                        message=str(item["message"]),
                        suggestion=str(item["suggestion"]),
                        guideline_id=item.get("guideline_id"),
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        result[page_id] = suggestions
    return result


def _encode_revisions(reports: list[PageReport]) -> str:
    """이메일 제목(원본 문서 제목)과 본문 맨 위 "Confluence에 붙여넣기" 블록을
    만드는 데 필요한 최소 정보만 JSON으로 직렬화한다. report_markdown과
    마찬가지로 hidden 필드로 화면에 실어 보내서, 이메일 발송 시 재분석 없이
    그대로 재사용한다."""
    return json.dumps(
        [
            {"title": r.page.title, "web_url": r.page.web_url, "revised_document": r.revised_document}
            for r in reports
        ],
        ensure_ascii=False,
    )


def _decode_revisions(revisions_json: str) -> list[dict]:
    if not revisions_json:
        return []
    try:
        raw = json.loads(revisions_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("title")]


def _build_email_subject(revisions: list[dict]) -> str:
    if not revisions:
        return "[AI Friendly 문서 개선 제안] 수정 제안"
    first_title = revisions[0]["title"]
    suffix = f" 외 {len(revisions) - 1}건" if len(revisions) > 1 else ""
    return f"[AI Friendly 문서 개선 제안] {first_title} 수정 제안{suffix}"


def _render_copyable_revision_block(revisions: list[dict]) -> str:
    """이메일 본문 맨 앞에 넣을, "그대로 복사해서 Confluence 새 페이지 소스에
    붙여넣기" 위한 블록을 만든다. 최종 수정본(평문 마크다운)을 Confluence의
    내장 "Markdown" 매크로로 감싸서, 사람이 읽는 서식이 아니라 매크로 XML
    텍스트 그대로 보여준다 - 그래야 전체 선택 → 복사 → Confluence 소스
    편집기에 붙여넣기가 그대로 통한다(렌더링된 서식을 복사하면 원본 마크업이
    아니라 브라우저가 임의로 변환한 HTML이 복사돼서 깨지기 쉽다).

    예전에는 우리가 직접 마크다운을 Confluence storage format(XHTML)
    태그로 변환했는데(구 confluence_storage.py), 표/중첩 목록처럼 복잡한
    구조에서 실제 붙여넣기 결과가 원본과 다르게 재현되는 경우가 많았다.
    지금은 변환을 직접 하지 않고 Markdown 매크로에 평문을 그대로 맡겨서,
    렌더링은 Confluence 자신의 마크다운 파서가 담당하게 한다.

    소스 편집기는 페이지 본문만 편집하고 제목은 별도 입력란이다 - 페이지
    제목은 원본 문서 제목을 그대로 쓰면 되므로 별도 제안 제목은 안내하지
    않는다. 원본 문서 링크는 본문에 포함돼야 의미가 있으므로, 매크로에
    감싸기 전 마크다운 맨 위에 링크 문법으로 끼워 넣고, 그 바로 아래에
    수정본 내용이 이어지게 한다.
    """
    blocks_with_content = [r for r in revisions if (r.get("revised_document") or "").strip()]
    if not blocks_with_content:
        return ""

    parts = [
        '<div style="margin-bottom:1.5rem;">',
        "<h2>📋 최종 수정 제안 (Confluence에 바로 붙여넣기)</h2>",
        "<p>아래 내용을 전체 선택해서 복사한 뒤, Confluence에서 새 페이지를 만들고 "
        "<strong>제목은 원본 문서 제목을 그대로 입력</strong>한 다음, 편집기 오른쪽 위 "
        "<strong>⋯(더보기) 메뉴 → 소스 편집기</strong>를 열어 그대로 붙여넣으면 서식이 "
        "적용된 페이지가 만들어집니다.</p>",
    ]
    for revision in blocks_with_content:
        revised_document = revision["revised_document"]
        title = revision["title"]
        web_url = revision.get("web_url") or ""

        # 원본 문서 링크는 본문 안에 있어야 의미가 있으므로, 매크로로 감싸기
        # 전 마크다운 맨 위에 마크다운 링크 문법 그대로 끼워 넣는다 -
        # Confluence의 마크다운 파서가 렌더링 시 실제 링크로 바꿔준다.
        if web_url:
            link_line = f"*원본 문서: [{escape_markdown_link_text(title)}]({web_url})*"
            source_with_link = f"{link_line}\n\n{revised_document}"
        else:
            source_with_link = revised_document

        macro = markdown_to_confluence_markdown_macro(source_with_link)
        if not macro.strip():
            continue

        parts.append(f"<h3>{html_module.escape(title)}</h3>")
        parts.append(
            '<pre style="white-space:pre-wrap;word-break:break-word;background:#f4f5f7;'
            'border:1px solid #ddd;border-radius:6px;padding:0.75rem;font-size:0.85rem;">'
            f"{html_module.escape(macro)}</pre>"
        )
    parts.append("</div><hr>")
    return "".join(parts)


@app.get("/analyze", response_class=HTMLResponse)
def analyze_form(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not db.get_credentials(user.id):
        return RedirectResponse("/settings?onboarding=1", status_code=303)
    return render(request, "analyze.html", core_guidelines=CORE_GUIDELINES, extra_guidelines=EXTRA_GUIDELINES)


@app.post("/analyze/fetch", response_class=HTMLResponse)
def analyze_fetch(request: Request, mode: str = Form(...), value: str = Form(...)):
    """Confluence 조회(빠름)와 AI 분석(규칙 검사 + LLM 검토, 느림)을 분리한 1단계.

    분석에 시간이 오래 걸린다는 피드백을 반영해, 우선 원본 문서만 빠르게
    가져와 보여주고, AI 분석은 사용자가 원할 때 별도 버튼으로 실행하게
    한다(/analyze POST가 2단계).
    """
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guideline_context = {"core_guidelines": CORE_GUIDELINES, "extra_guidelines": EXTRA_GUIDELINES}

    try:
        pages = _fetch_pages(user, mode, value)
    except SecurityConfigError as e:
        return render(request, "analyze.html", error=str(e), mode=mode, value=value, **guideline_context)
    except Exception as e:  # noqa: BLE001 - 사용자에게 원인 표시
        return render(
            request, "analyze.html", error=f"Confluence 조회 중 오류: {e}", mode=mode, value=value, **guideline_context
        )

    if not pages:
        return render(
            request,
            "analyze.html",
            error="조회된 페이지가 없습니다.",
            mode=mode,
            value=value,
            **guideline_context,
        )

    fetched_pages = [
        {
            "page": page,
            "original_document": storage_html_to_plain_text(
                page.storage_html, max_chars=None, attachments=page.attachments
            ),
        }
        for page in pages
    ]
    return render(
        request, "analyze.html", mode=mode, value=value, fetched_pages=fetched_pages, **guideline_context
    )


@app.post("/analyze", response_class=HTMLResponse)
def analyze_submit(request: Request, mode: str = Form(...), value: str = Form(...)):
    """"AI 분석" 버튼 - 규칙 검사 + LLM 찾기/수정안까지만 수행한다 (최종
    수정본 생성은 /analyze/revise가 별도로 담당). 가장 자주 실패하는
    수정본 생성 호출을 여기서 하지 않으므로, 이 단계는 상대적으로 빠르고
    안정적이다.
    """
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guideline_context = {"core_guidelines": CORE_GUIDELINES, "extra_guidelines": EXTRA_GUIDELINES}

    try:
        reports = _run_findings_analysis(user, mode, value)
    except SecurityConfigError as e:
        return render(request, "analyze.html", error=str(e), mode=mode, value=value, **guideline_context)
    except Exception as e:  # noqa: BLE001 - 사용자에게 원인 표시
        return render(
            request, "analyze.html", error=f"Confluence 조회 중 오류: {e}", mode=mode, value=value, **guideline_context
        )

    if not reports:
        return render(
            request,
            "analyze.html",
            error="분석할 페이지를 찾지 못했습니다.",
            mode=mode,
            value=value,
            **guideline_context,
        )

    report_markdown = render_report(reports)
    # fenced_code가 없으면 최종 수정본을 감싼 ```...``` 블록이 코드 블록으로
    # 인식되지 않고 일반 문단 취급돼서, 그 안의 줄바꿈이 markdown 문법상
    # 그냥 공백으로 뭉개져버린다("줄바꿈이 다 깨진다"는 증상의 원인).
    report_html = md.markdown(report_markdown, extensions=["tables", "fenced_code"])
    return render(
        request,
        "analyze.html",
        mode=mode,
        value=value,
        report_html=report_html,
        report_markdown=report_markdown,
        reports=reports,
        # "최종 수정본 제안" 버튼을 누르면 이 문제 목록을 이어서 참고할 수
        # 있도록 hidden 필드로 실어 보낸다.
        suggestions_json=_encode_suggestions_by_page(reports),
        revisions_json=_encode_revisions(reports),
        **guideline_context,
    )


@app.post("/analyze/revise", response_class=HTMLResponse)
def analyze_revise(
    request: Request,
    mode: str = Form(...),
    value: str = Form(...),
    suggestions_json: str = Form(""),
):
    """"최종 수정본 제안" 버튼 - 문서 전체 재작성 LLM 호출만 (재)수행한다.

    LLM 호출 중 출력이 가장 길고 가장 자주 실패하는 부분이라, "AI 분석"
    (규칙 검사 + 찾기/수정안)과 완전히 분리했다 - 실패해도 AI 분석을 다시
    돌릴 필요 없이 이 버튼만 다시 누르면 된다. suggestions_json이 있으면
    (AI 분석을 먼저 돌린 경우) 그 결과를 참고해 더 구체적인 수정본을
    만들고, 없으면(바로 이 버튼부터 누른 경우) 참고 없이 만든다.
    """
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guideline_context = {"core_guidelines": CORE_GUIDELINES, "extra_guidelines": EXTRA_GUIDELINES}

    try:
        pages = _fetch_pages(user, mode, value)
    except SecurityConfigError as e:
        return render(request, "analyze.html", error=str(e), mode=mode, value=value, **guideline_context)
    except Exception as e:  # noqa: BLE001 - 사용자에게 원인 표시
        return render(
            request, "analyze.html", error=f"Confluence 조회 중 오류: {e}", mode=mode, value=value, **guideline_context
        )

    if not pages:
        return render(
            request,
            "analyze.html",
            error="조회된 페이지가 없습니다.",
            mode=mode,
            value=value,
            **guideline_context,
        )

    suggestions_by_page = _decode_suggestions_by_page(suggestions_json)

    reports = []
    for page in pages:
        # AI 분석을 이미 돌린 페이지면 그 결과를 참고하고, 아니면 빈
        # 목록으로(그래도 동작한다 - 시스템 프롬프트의 가이드라인만으로 다시
        # 쓴다) 수정본을 생성한다.
        prior_suggestions = suggestions_by_page.get(page.id, [])
        revised_document, revision_error = generate_page_revision(page, prior_suggestions)
        suggestions = list(prior_suggestions)
        if revision_error:
            suggestions.append(
                Suggestion(
                    rule_id="llm-revision-error",
                    severity=Severity.INFO,
                    location="문서 전체",
                    message="문서 전체 수정본을 만들지 못했습니다.",
                    suggestion=revision_error,
                )
            )
        reports.append(
            PageReport(
                page=page,
                suggestions=suggestions,
                # AI 분석을 이미 거친 페이지만 "LLM으로 확인됨"으로 채점한다 -
                # 안 거쳤으면 findings 자체가 검증되지 않았으므로 가이드라인
                # 점수는 "확인 불가"로 남아야 한다.
                guideline_score=score_document(suggestions, llm_configured=page.id in suggestions_by_page),
                original_document=storage_html_to_plain_text(
                    page.storage_html, max_chars=None, attachments=page.attachments
                ),
                revised_document=revised_document,
            )
        )

    report_markdown = render_report(reports)
    report_html = md.markdown(report_markdown, extensions=["tables", "fenced_code"])
    return render(
        request,
        "analyze.html",
        mode=mode,
        value=value,
        report_html=report_html,
        report_markdown=report_markdown,
        reports=reports,
        suggestions_json=_encode_suggestions_by_page(reports),
        revisions_json=_encode_revisions(reports),
        **guideline_context,
    )


@app.post("/analyze/download")
def analyze_download(
    request: Request,
    mode: str = Form(...),
    value: str = Form(...),
    report_markdown: str = Form(""),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # /analyze에서 이미 만들어둔 리포트가 hidden 필드로 같이 넘어오면 그대로
    # 쓴다 - Confluence 재조회 + LLM 재검토(findings/fixes 호출과 수정본
    # 생성 호출, 페이지당 최대 2번씩)를 다시 돌릴 필요가 없다. 예전 방식대로
    # mode/value만 오면(예: 외부에서 이 엔드포인트를 직접 호출) 그때만
    # 새로 분석한다.
    if not report_markdown:
        try:
            reports = _run_analysis(user, mode, value)
        except Exception as e:  # noqa: BLE001 - 다운로드 실패 사유를 그대로 보여줌
            return PlainTextResponse(f"리포트를 생성하지 못했습니다: {e}", status_code=400)
        report_markdown = render_report(reports)

    return PlainTextResponse(
        report_markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="ai-friendly-doc-report.md"'},
    )


@app.post("/analyze/email", response_class=HTMLResponse)
def analyze_email(
    request: Request,
    mode: str = Form(...),
    value: str = Form(...),
    report_markdown: str = Form(""),
    page_count: int = Form(0),
    revisions_json: str = Form(""),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guideline_context = {"core_guidelines": CORE_GUIDELINES, "extra_guidelines": EXTRA_GUIDELINES}
    # 별도 입력란 없이 로그인 아이디 그대로 사내 메일 주소로 사용한다
    # (예: "hong.gildong" 로그인 → "hong.gildong@samsung.com").
    email = f"{user.username}@samsung.com"

    reports = None
    revisions: list[dict] = []
    # 다운로드와 마찬가지로, /analyze에서 이미 만들어둔 리포트가 hidden
    # 필드로 넘어오면 재사용한다 - 그렇지 않으면 화면에 이미 보이는 결과를
    # 메일로 보내는 것뿐인데도 Confluence 재조회 + LLM 재검토가 통째로 다시
    # 돌아서 오래 걸린다.
    if not report_markdown:
        try:
            reports = _run_analysis(user, mode, value)
        except SecurityConfigError as e:
            return render(request, "analyze.html", error=str(e), mode=mode, value=value, **guideline_context)
        except Exception as e:  # noqa: BLE001 - 사용자에게 원인 표시
            return render(
                request,
                "analyze.html",
                error=f"Confluence 조회 중 오류: {e}",
                mode=mode,
                value=value,
                **guideline_context,
            )

        if not reports:
            return render(
                request,
                "analyze.html",
                error="분석할 페이지를 찾지 못했습니다.",
                mode=mode,
                value=value,
                **guideline_context,
            )

        report_markdown = render_report(reports)
        page_count = len(reports)
        revisions = json.loads(_encode_revisions(reports))
    else:
        revisions = _decode_revisions(revisions_json)

    # fenced_code가 없으면 최종 수정본을 감싼 ```...``` 블록이 코드 블록으로
    # 인식되지 않고 일반 문단 취급돼서, 그 안의 줄바꿈이 markdown 문법상
    # 그냥 공백으로 뭉개져버린다("줄바꿈이 다 깨진다"는 증상의 원인).
    report_html = md.markdown(report_markdown, extensions=["tables", "fenced_code"])
    render_context = dict(
        mode=mode,
        value=value,
        report_html=report_html,
        report_markdown=report_markdown,
        reports=reports,
        **guideline_context,
    )

    # 메일 본문은 화면에 보이는 report_html과 다르다 - 최종 수정본을
    # Confluence에 바로 붙여넣을 수 있는 블록을 맨 앞에 추가한다.
    email_body_html = _render_copyable_revision_block(revisions) + report_html

    try:
        send_report_email(
            email,
            subject=_build_email_subject(revisions),
            body_html=email_body_html,
        )
    except MailConfigError as e:
        return render(request, "analyze.html", error=str(e), **render_context)

    return render(request, "analyze.html", email_sent=email, **render_context)
