# ai-friendly-doc

사내 Confluence 문서를 읽어, AI가 파싱/이해하기 좋은 형태인지 점검하고
**개선 제안 리포트(Markdown)**를 만들어주는 도구입니다.

## 설계 원칙

- **읽기 전용**: Confluence Write API를 사용하지 않습니다. 원본 문서를 절대
  수정하지 않고, "이렇게 고치면 좋겠다"는 제안만 생성합니다. 실제 반영은
  문서 작성자가 직접 판단해서 수동으로 합니다.
- **규칙 기반 + 확장 가능**: 개선 규칙은 `Rule` 인터페이스를 구현하는 플러그인
  형태입니다. 현재 포함된 규칙은 구조적인 것 위주의 스타터 세트이며, 조직에
  맞는 규칙(용어 통일, 금칙어, LLM 기반 재작성 제안 등)을 자유롭게 추가할 수
  있습니다.

## 설치

```bash
pip install -e ".[dev]"
```

## 설정

`.env.example`을 복사해 `.env`로 만들고 값을 채웁니다.

```bash
cp .env.example .env
```

- **Confluence Cloud**: `CONFLUENCE_AUTH_TYPE=basic` + `CONFLUENCE_EMAIL` +
  Atlassian API 토큰(`CONFLUENCE_API_TOKEN`).
  토큰 발급: https://id.atlassian.com/manage-profile/security/api-tokens
- **Confluence Server/Data Center (PAT 사용 가능한 경우)**: `CONFLUENCE_AUTH_TYPE=bearer` +
  Personal Access Token(`CONFLUENCE_API_TOKEN`).
- **Confluence Server/Data Center (PAT 발급이 안 되거나 안 쓰는 경우)**:
  `CONFLUENCE_AUTH_TYPE=userpass` + 계정 ID(`CONFLUENCE_EMAIL`) + 비밀번호(`CONFLUENCE_API_TOKEN`).
  내부적으로 basic과 동일하게 HTTP Basic Auth로 전송되며, 계정 ID는 이메일 형식이
  아니어도 된다.

`CONFLUENCE_BASE_URL`은 Cloud 기준 `https://<domain>.atlassian.net/wiki` 형태입니다.

사내 Confluence가 자체 서명 인증서를 써서 TLS 검증이 실패하는 경우
`CONFLUENCE_VERIFY_SSL=false`로 끌 수 있습니다 (기본값 `true`). 신뢰할 수 있는
사내망 안에서만 쓰고, 공인 인증서를 쓰는 서버에는 절대 끄지 마세요.

## 사용법 (CLI)

특정 페이지 ID 분석:

```bash
ai-friendly-doc --page-id 123456 --page-id 234567 -o report.md
```

스페이스 전체 분석:

```bash
ai-friendly-doc --space-key ENG -o report.md
```

`-o`를 생략하면 표준출력으로 리포트가 출력됩니다.

## 웹 UI

여러 사용자가 브라우저에서 로그인해서 각자 자신의 Confluence 토큰으로
문서를 분석할 수 있는 웹 UI(FastAPI)도 포함되어 있습니다.

```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # FERNET_KEY에 채워넣기
python -c "import secrets; print(secrets.token_hex(32))"                                    # SESSION_SECRET에 채워넣기

ai-friendly-doc-web
# 또는: python -m ai_friendly_doc.web
```

기본적으로 http://127.0.0.1:12345 에서 뜹니다. `HOST`/`PORT` 환경변수로 바인딩을
바꿀 수 있습니다(사내망에 공개하려면 `HOST=0.0.0.0`).

흐름:
1. `/register`에서 계정 생성 (아이디 + 비밀번호, bcrypt로 해시 저장)
2. `/settings`에서 본인의 인증 방식(Cloud는 basic+이메일, Server·DC는 bearer+PAT
   또는 userpass+계정 ID/비밀번호) / API 토큰(또는 비밀번호) 입력 → 값은 `FERNET_KEY`로
   암호화되어 DB에 저장. Confluence Base URL은 `.env`의 `CONFLUENCE_BASE_URL`이
   설정돼 있으면 그 값이 모든 사용자에게 고정 적용되어(입력창이 읽기 전용으로
   표시됨) 따로 입력할 필요가 없고, 비워두면 사용자가 각자 입력한다.
   `CONFLUENCE_VERIFY_SSL=false`도 마찬가지로 배포 단위 설정이라 `.env`에서만
   끄면 모든 사용자에게 적용된다.
3. `/analyze`에서 페이지 ID(들) 또는 스페이스 키를 입력해 분석 실행 →
   결과는 화면에 바로 렌더링되고, "Markdown으로 다운로드" 버튼으로 파일도
   받을 수 있음. Write API는 여전히 호출하지 않으므로 원본 문서는 변경되지
   않습니다.

CLI와 마찬가지로 사용자별 토큰은 조회에만 쓰이며, 각 사용자는 본인이 저장한
토큰으로만 조회가 가능합니다(다른 사용자의 토큰에 접근할 방법 없음).

> 운영 배포 시에는 HTTPS 뒤에 두는 것을 권장합니다(세션 쿠키/토큰 입력이
> 평문 HTTP로 오가지 않도록).

### 사용자/토큰 저장소: SQLite(로컬) vs PostgreSQL(서버)

`DATABASE_URL`을 지정하지 않으면 로컬 SQLite 파일(`AI_FRIENDLY_DOC_DB`, 기본
`ai_friendly_doc.db`)을 쓴다. 서버에서는 PostgreSQL을 쓰도록 아래처럼
`DATABASE_URL`을 지정하면 된다(테이블은 앱 기동 시 자동 생성됨):

```
DATABASE_URL=postgresql+psycopg2://<user>:<password>@<host>:5432/<dbname>
```

## Docker로 배포하기

이 서버에는 이미 PostgreSQL과 vLLM이 docker로 떠 있고, 그 postgres는 호스트에
포트가 노출되어 있다고 가정한다. 이 앱은 별도 컨테이너로 떠서 호스트에 노출된
포트로 postgres에 접속하는 구조다 (같은 docker 네트워크에 조인하지 않음).

1. **앱 전용 DB/유저 생성** (기존 postgres 컨테이너 안에서 슈퍼유저로 1회 실행):

   ```bash
   docker exec -i <postgres-container-name> psql -U postgres < scripts/init_postgres.sql
   ```

   `scripts/init_postgres.sql`의 비밀번호(`change-me`)는 실제 운영 값으로 바꿔서 실행할 것.

2. **`.env` 준비**

   ```bash
   cp .env.example .env
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # FERNET_KEY
   python -c "import secrets; print(secrets.token_hex(32))"                                    # SESSION_SECRET
   ```

   `.env`에서 `DATABASE_URL`의 주석을 풀고 값을 채운다. 앱 컨테이너는
   `host.docker.internal`로 호스트에 접근하므로(= `docker-compose.yml`의
   `extra_hosts` 설정), postgres가 호스트의 5432 포트로 노출되어 있다면:

   ```
   DATABASE_URL=postgresql+psycopg2://sait-people:change-me@host.docker.internal:5432/people_user_db
   ```

3. **빌드 & 기동**

   ```bash
   docker compose up -d --build
   ```

   기본적으로 호스트의 12345번 포트로 뜬다 (`docker-compose.yml`의 `ports` 수정 가능).

4. 로그 확인: `docker compose logs -f web`

vLLM은 현재 이 앱에서 사용하지 않지만(향후 LLM 기반 재작성 제안에 쓸 수 있음),
같은 호스트-포트 노출 방식으로 나중에 연결할 수 있다.

### 서버에 올리기 전, Windows/WSL에서 로컬 테스트

서버는 postgres가 이미 docker로 떠 있어서 위 방식(호스트 포트로 접속)을 쓰지만,
로컬 PC에서는 그렇게 맞출 필요 없이 `docker-compose.local-test.yml`로 테스트 전용
postgres 컨테이너를 앱과 같은 docker 네트워크에 띄워서 쓰는 게 훨씬 간단하다
(Windows에 설치된 postgres를 WSL에서 접속하려면 리스닝 주소/방화벽/백신 설정을
일일이 맞춰야 해서 번거롭다).

```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # FERNET_KEY
python -c "import secrets; print(secrets.token_hex(32))"                                    # SESSION_SECRET
# DATABASE_URL은 채우지 않아도 됨 (아래 오버레이가 자동으로 지정함)

docker compose -f docker-compose.yml -f docker-compose.local-test.yml up -d --build
```

이 명령은 postgres 컨테이너(`postgres:16-alpine`, 유저 `sait-people` / DB
`people_user_db`로 자동 생성됨)와 web 컨테이너를 같이 띄우고, web은 `DATABASE_URL`이
`postgres` 서비스 이름으로 자동 지정되어 접속한다. Windows 브라우저에서
http://localhost:12345 로 바로 접속해서 테스트하면 된다 (WSL2가 자동으로 포트를
Windows localhost로 포워딩해준다).

유저/비밀번호/DB명은 하드코딩되어 있지 않고 `.env`의 `LOCAL_TEST_DB_USER` /
`LOCAL_TEST_DB_PASSWORD` / `LOCAL_TEST_DB_NAME`으로 바꿀 수 있다 (지정 안 하면
위 기본값 사용, `.env.example` 참고). 테스트 전용 값이라도 git에는 올라가지
않는 `.env`에서만 관리한다.

종료:
```bash
docker compose -f docker-compose.yml -f docker-compose.local-test.yml down
# DB 데이터까지 지우려면: ... down -v
```

`docker-compose.local-test.yml`은 로컬 테스트 전용이며, 파일명을 일부러
`docker-compose.override.yml`로 하지 않았다(그 이름은 `docker compose up`에서
자동 병합되는데, 서버에서 무심코 그렇게 실행하면 이 테스트용 postgres가 같이
떠버릴 수 있어서). 항상 `-f docker-compose.local-test.yml`을 명시할 때만 적용된다.

## 리포트 예시 구조

```
# AI-Friendly 문서 개선 제안 리포트

| 페이지 | 제안 수 | 심각 | 경고 | 참고 |
| --- | --- | --- | --- | --- |
| 배포 가이드 | 3 | 0 | 2 | 1 |

## 배포 가이드
- 원본: https://your-domain.atlassian.net/wiki/spaces/ENG/pages/123456
...

### [🟡 경고] '사전 준비' 섹션의 표 #1 (4행 x 3열)
- 규칙: `missing-table-header`
- 문제: 표에 헤더 행이 없어 각 열이 무엇을 의미하는지 문맥 없이는 알기 어려움
- 제안: 첫 번째 행을 헤더(th)로 지정해 각 열의 의미를 명시하세요.
```

## 포함된 스타터 규칙

| 규칙 ID | 설명 |
| --- | --- |
| `heading-hierarchy-skip` | 제목 레벨이 갑자기 건너뛰는 경우 (H1 → H3 등) |
| `missing-h1` | 문서에 최상위 제목(H1)이 없는 경우 |
| `missing-table-header` | 헤더 행이 없는 표 |
| `missing-alt-text` | 대체 텍스트가 없는 이미지 |
| `ambiguous-link-text` | "여기", "click here" 등 맥락 없이 이해 불가능한 링크 텍스트 |
| `long-paragraph` | 지나치게 긴 문단 (기본 120단어 초과) |

## LLM 심층 검토 (선택)

스타터 규칙은 구조적인 문제(제목 계층, 표 헤더, alt 텍스트 등)만 잡습니다.
`.env`에 `LLM_BASE_URL`을 설정하면, 실제 문서 내용을 LLM에게 읽혀서 "AI가 이
문서만 보고 정확히 이해할 수 있는가" 관점의 문제까지 같이 찾아줍니다:

- 문맥 없이는 무엇을 가리키는지 알 수 없는 지시어("이것", "위 내용" 등)
- 설명 없이 쓰인 사내 용어/줄임말/프로젝트 코드명
- 이 문서만 봐서는 알 수 없는, 생략된 전제나 배경 설명
- 결론이나 의도가 불명확한 문단
- 시간이 지나면 틀리게 되는 상대적 표현("최근에", "지난주")

vLLM 등 OpenAI 호환 API 엔드포인트를 그대로 쓸 수 있습니다 (`.env.example`의
LLM 관련 항목 참고). 설정돼 있으면 CLI/웹 UI 모두에서 매 분석마다 자동으로
같이 실행되며, 별도로 켜고 끄는 옵션은 없습니다. LLM 호출이 실패해도 규칙
기반 결과는 그대로 리포트에 남고, 실패 사실만 별도 항목(`llm-review-error`)
으로 표시됩니다. 결과는 규칙 기반 제안과 같은 리포트에 `llm-review`
규칙 ID로 섞여서 나타납니다.

## 새 규칙 추가하기

`src/ai_friendly_doc/rules/base.py`의 `Rule`을 상속해 `check(doc: ParsedDoc)`을
구현하고, `src/ai_friendly_doc/rules/__init__.py`의 `DEFAULT_RULES`에 등록하면
됩니다. `ParsedDoc`은 문서의 제목/표/이미지/링크/문단을 순서대로 담고 있습니다
(`src/ai_friendly_doc/parser.py` 참고).

## 테스트

```bash
pytest
```

## 프로젝트 구조

```
src/ai_friendly_doc/
  config.py             # .env 기반 설정 로더 (CLI용)
  confluence_client.py  # Confluence REST API 읽기 전용 클라이언트
  parser.py             # storage format(XHTML) -> ParsedDoc 변환
  analyzer.py           # 페이지 하나를 파싱 + 규칙(+ 설정 시 LLM) 적용
  llm_review.py         # LLM(vLLM 등 OpenAI 호환 API) 기반 심층 검토
  report.py             # 제안 목록 -> Markdown 리포트
  cli.py                # CLI 진입점
  rules/
    base.py             # Rule / Suggestion 기본 클래스
    starter.py           # 스타터 규칙 구현
  web/
    app.py               # FastAPI 라우트 (회원가입/로그인/설정/분석)
    db.py                 # 사용자/Confluence 인증정보 저장소 (SQLAlchemy, SQLite/PostgreSQL 겸용)
    security.py           # 비밀번호 해시(bcrypt), 토큰 암호화(Fernet)
    __main__.py            # `python -m ai_friendly_doc.web` 진입점
    templates/             # Jinja2 HTML 템플릿
tests/
  test_rules.py
  test_confluence_client.py
  test_config.py
  test_fixed_base_url.py
  test_llm_review.py
  test_analyzer_llm_integration.py
Dockerfile
docker-compose.yml               # 서버 배포용 (호스트 노출 포트의 기존 postgres에 접속)
docker-compose.local-test.yml    # Windows/WSL 로컬 테스트용 오버레이 (postgres 컨테이너 포함)
scripts/init_postgres.sql   # 서버 postgres에 앱 전용 DB/유저 생성
```
