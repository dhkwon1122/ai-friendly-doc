"""웹 UI: 사용자가 로그인해서 본인 Confluence 토큰을 저장하고,
페이지/스페이스를 분석해 개선 제안 리포트를 브라우저에서 바로 확인할 수 있게 한다.
"""

from __future__ import annotations

import os
from pathlib import Path

import markdown as md
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from ..analyzer import analyze_page
from ..config import ConfluenceConfig, parse_bool_env
from ..confluence_client import ConfluenceClient
from ..guidelines import CORE_GUIDELINES, EXTRA_GUIDELINES
from ..report import render_report
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
    )
    return ConfluenceClient(config)


def _run_analysis(user: db.User, mode: str, value: str):
    client = _build_client(user)
    reports = []
    if mode == "page_ids":
        page_ids = [p.strip() for p in value.replace(",", "\n").splitlines() if p.strip()]
        for page_id in page_ids:
            reports.append(analyze_page(client.get_page(page_id)))
    else:
        for page in client.iter_space_pages(value.strip()):
            reports.append(analyze_page(page))
    return reports


@app.get("/analyze", response_class=HTMLResponse)
def analyze_form(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not db.get_credentials(user.id):
        return RedirectResponse("/settings?onboarding=1", status_code=303)
    return render(request, "analyze.html", core_guidelines=CORE_GUIDELINES, extra_guidelines=EXTRA_GUIDELINES)


@app.post("/analyze", response_class=HTMLResponse)
def analyze_submit(request: Request, mode: str = Form(...), value: str = Form(...)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guideline_context = {"core_guidelines": CORE_GUIDELINES, "extra_guidelines": EXTRA_GUIDELINES}

    try:
        reports = _run_analysis(user, mode, value)
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
    report_html = md.markdown(report_markdown, extensions=["tables"])
    return render(
        request,
        "analyze.html",
        mode=mode,
        value=value,
        report_html=report_html,
        report_markdown=report_markdown,
        reports=reports,
        **guideline_context,
    )


@app.post("/analyze/download")
def analyze_download(request: Request, mode: str = Form(...), value: str = Form(...)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

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
def analyze_email(request: Request, mode: str = Form(...), value: str = Form(...)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guideline_context = {"core_guidelines": CORE_GUIDELINES, "extra_guidelines": EXTRA_GUIDELINES}
    # 별도 입력란 없이 로그인 아이디 그대로 사내 메일 주소로 사용한다
    # (예: "hong.gildong" 로그인 → "hong.gildong@samsung.com").
    email = f"{user.username}@samsung.com"

    try:
        reports = _run_analysis(user, mode, value)
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
    report_html = md.markdown(report_markdown, extensions=["tables"])
    render_context = dict(
        mode=mode,
        value=value,
        report_html=report_html,
        report_markdown=report_markdown,
        reports=reports,
        **guideline_context,
    )

    try:
        send_report_email(
            email,
            subject=f"[ai-friendly-doc] 분석 리포트 ({len(reports)}개 페이지)",
            body_html=report_html,
        )
    except MailConfigError as e:
        return render(request, "analyze.html", error=str(e), **render_context)

    return render(request, "analyze.html", email_sent=email, **render_context)
