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

Personal Access Token(PAT) 기반 Bearer 인증만 지원합니다 (`CONFLUENCE_API_TOKEN`
자리에 PAT을 넣습니다). 계정 ID + 비밀번호로 하는 HTTP Basic Auth는 지원하지
않습니다 - 다수의 사내 Confluence Server/DC가 관리자 설정으로 Basic Auth
자체를 꺼두고 있어서(`"Basic Authentication has been disabled on this
instance"`), 자격증명이 맞아도 Basic Auth 요청은 무조건 거부되기 때문입니다.
PAT은 Confluence 프로필 > **Personal Access Tokens** 메뉴에서 발급받을 수
있습니다 (Confluence 7.9+ Server/DC 기준. Cloud는 API 토큰을 그대로 넣어도
됩니다).

`CONFLUENCE_BASE_URL`은 Cloud 기준 `https://<domain>.atlassian.net/wiki` 형태입니다.

사내 Confluence가 자체 서명 인증서를 써서 TLS 검증이 실패하는 경우
`CONFLUENCE_VERIFY_SSL=false`로 끌 수 있습니다 (기본값 `true`). 신뢰할 수 있는
사내망 안에서만 쓰고, 공인 인증서를 쓰는 서버에는 절대 끄지 마세요.

### 조회가 "403 Forbidden"으로 실패할 때

1. **응답 본문에 `"Basic Authentication has been disabled on this
   instance"`가 보인다면** - 계정 ID/비밀번호(Basic Auth) 방식 자체가 서버
   관리자 설정으로 막혀 있다는 뜻입니다. 자격증명을 아무리 바꿔도 코드로는
   해결할 수 없고, 위 설정 안내대로 **Personal Access Token(PAT)을 발급받아
   `CONFLUENCE_API_TOKEN`(웹 UI는 `/settings`)에 넣어야** 합니다.
2. PAT이 맞는데도 403이 나고, **같은 페이지를 브라우저로는 정상적으로 볼 수
   있다면** - 앞단 WAF/게이트웨이가 브라우저처럼 보이지 않는 요청(파이썬
   `requests`의 기본 User-Agent 등)을 봇으로 간주해 차단하는 경우가 흔합니다.
   기본적으로 일반적인 Chrome User-Agent를 흉내내도록 되어 있어 대부분은
   이걸로 해결되고, 그래도 안 되면 `.env`의 `CONFLUENCE_USER_AGENT`에 실제
   브라우저의 User-Agent 문자열을 그대로 넣어보세요 (브라우저 개발자 도구 >
   네트워크 탭에서 아무 요청이나 열어 확인 가능).
3. 웹 UI에서 에러 메시지의 "PAT 길이: 0" 같은 표시가 보인다면 `/settings`에
   토큰이 아예 저장되지 않은 것이니 다시 입력해서 저장하세요.
4. 그래도 안 되면 IP 허용 목록 등 네트워크 단의 문제일 가능성이 큽니다 -
   이건 코드로 해결할 수 없고 사내 인프라/보안팀 확인이 필요합니다.

에러 메시지에는 실제 요청에 쓰인 base_url과 토큰 길이(토큰 값 자체는
제외), 서버 응답 본문이 있다면 그 내용까지 그대로 표시되니 확인해보세요.

### 조회가 "401 Unauthorized"로 실패할 때

403과 달리 401은 요청이 인증 단계까지는 도달했지만 토큰 자체가 거부됐다는
뜻입니다. 대체로 다음 중 하나입니다:

1. **PAT이 만료됐거나 잘못 발급됨** - Confluence 프로필의 Personal Access
   Tokens 메뉴에서 유효 기간과 값을 다시 확인하세요.
2. **토큰을 복사-붙여넣기하면서 앞뒤 공백/개행이 섞여 들어감** - 겉보기엔
   같은 토큰이라도 Authorization 헤더 값이 미묘하게 달라져 401이 납니다.
   이 도구는 토큰을 저장/전송할 때 자동으로 strip하므로 이 자체는 코드에서
   방어하고 있지만, 애초에 잘못된(잘린) 값을 복사했다면 여전히 401이 날 수
   있으니 다시 복사해서 저장해보세요.
3. **Accept 헤더 관련** - 일부 사내 게이트웨이는 `Accept: application/json`
   없이 오는 요청을 REST API가 아니라 브라우저용 로그인 흐름으로 취급해
   인증 결과가 달라집니다. 이 도구는 기본적으로 이 헤더를 보냅니다.
4. 그래도 안 되면 요청 자체(`curl -H "Authorization: Bearer <PAT>" ...`)를
   Confluence 관리자/보안팀과 함께 확인해보세요 - 이 시점부터는 토큰
   발급/권한 쪽 문제일 가능성이 큽니다.

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
# CONFLUENCE_BASE_URL도 반드시 채워야 함 (아래 참고, 안 채우면 기동 자체가 실패함)

ai-friendly-doc-web
# 또는: python -m ai_friendly_doc.web
```

기본적으로 http://127.0.0.1:12345 에서 뜹니다. `HOST`/`PORT` 환경변수로 바인딩을
바꿀 수 있습니다(사내망에 공개하려면 `HOST=0.0.0.0`).

웹 UI는 `SESSION_SECRET`과 마찬가지로 `.env`의 `CONFLUENCE_BASE_URL`이 **필수**입니다
(설정 안 하면 기동 시점에 바로 에러를 내고 멈춥니다). 사용자가 각자 다른 Base
URL을 직접 입력하는 경로는 없고, 모든 사용자에게 이 값 하나로 고정 적용됩니다
(`/settings` 화면에는 읽기 전용으로만 표시됨) - 여러 인스턴스가 섞여 저장되는
걸 막고, DB의 `confluence_credentials` 테이블을 다른 앱과 공유하기도 쉽게 하기
위함입니다. `CONFLUENCE_VERIFY_SSL=false`도 마찬가지로 배포 단위 설정이라
`.env`에서만 끄면 모든 사용자에게 적용됩니다.

흐름:
1. `/register`에서 계정 생성 (아이디 + 비밀번호, bcrypt로 해시 저장)
2. `/settings`에서 본인의 Confluence Personal Access Token(PAT)만 입력 →
   값은 `FERNET_KEY`로 암호화되어 DB에 저장. 계정 ID + 비밀번호(Basic Auth)
   방식은 지원하지 않습니다(위 참고). Confluence Base URL은 입력할 필요가
   없습니다(위 참고).
3. `/analyze`에서 페이지 ID(들)를 입력합니다. 아래 세 버튼은 처음부터
   모두 화면에 떠 있고, 서로 독립적으로 실행할 수 있습니다(순서를
   지킬 필요 없음 - 어느 버튼이든 바로 눌러도 됩니다):
   - **문서 조회**: Confluence에서 원본만 빠르게 가져와 보여줍니다
     (LLM 호출 없음).
   - **AI 분석**: 규칙 검사 + LLM로 문제/수정안 찾기를 수행합니다.
     최종 수정본 생성은 포함하지 않아서 상대적으로 빠르고 안정적입니다.
   - **최종 수정본 제안**: 문서 전체를 다시 쓴 최종 수정본만 별도로
     생성합니다. LLM 호출 중 출력이 가장 길어서 실패할 때가 있는데,
     AI 분석과 완전히 분리돼 있어서 실패해도 **이 버튼만 다시 누르면**
     됩니다 - AI 분석을 다시 돌릴 필요가 없습니다. AI 분석을 먼저
     돌렸다면 그 결과(찾은 문제 목록)를 참고해서 더 구체적인 수정본을
     만들고, 안 돌렸다면 참고 없이 바로 만듭니다.

   AI 분석/최종 수정본 제안 결과는 화면에 바로 렌더링되고, "Markdown으로
   다운로드" 버튼으로 파일도 받을 수 있고, "이메일로 받기" 버튼으로
   리포트를 메일로도 받을 수 있습니다(메일 API 설정 필요, 아래 참고).
   별도 입력 없이 로그인 아이디 그대로 `<아이디>@samsung.com`으로
   발송됩니다. 각 페이지 섹션에는 원본 Confluence 페이지로 바로 이동할
   수 있는 링크가 포함됩니다. Write API는 여전히 호출하지 않으므로
   원본 문서는 변경되지 않습니다.

   스페이스 전체 조회(스페이스 키로 여러 페이지를 한 번에 분석하는 기능)는
   현재 화면에서 숨겨져 있습니다 - 페이지 단위 조회 위주로 쓰는 흐름이
   자리 잡을 때까지는 잠시 넣어뒀습니다. 라우트/로직 자체는 남아있어서
   `/analyze` POST에 `mode=space_key`를 직접 보내면 여전히 동작합니다
   (필요해지면 화면에 다시 노출하면 됩니다).

CLI와 마찬가지로 사용자별 토큰은 조회에만 쓰이며, 각 사용자는 본인이 저장한
토큰으로만 조회가 가능합니다(다른 사용자의 토큰에 접근할 방법 없음).

> 운영 배포 시에는 HTTPS 뒤에 두는 것을 권장합니다(세션 쿠키/토큰 입력이
> 평문 HTTP로 오가지 않도록).

### 이메일로 리포트 받기 (선택)

SMTP가 아니라 사내 메일 발송 REST API(기본값 `openapi.samsung.net`)를
씁니다. JSON을 그대로 요청 본문(body)에 담아 POST합니다(multipart/form-data
아님). `.env`에 `MAIL_API_TOKEN` / `MAIL_API_SYSTEM_ID` / `MAIL_API_USER_ID`
를 설정하면 `/analyze` 결과 화면에 "이메일로 받기" 버튼이 나옵니다.
로그인 아이디 그대로 `<아이디>@samsung.com`으로 보내며, 셋 중 하나라도
없으면 버튼을 눌러도 설정이 안 됐다는 안내가 뜹니다. 자세한 환경변수는
`.env.example`을 참고하세요.

**메일 제목**은 `[AI Friendly 문서 개선 제안] <원본 문서 제목> 수정 제안`
형식입니다(여러 페이지를 한 번에 분석했다면 첫 페이지 제목 뒤에
"외 N건"이 붙습니다).

**메일 본문 맨 앞**에는 최종 수정본을 **Confluence에 바로 붙여넣을 수
있는 형태**로 담은 "📋 최종 수정 제안" 블록이 옵니다 - 그 아래로 화면에서
보던 요약 표/가이드라인 점수/발견된 문제 목록이 이어집니다. 이 블록은
LLM이 만든 평문 수정본(제목 `#`, 목록 `-`, 표 `| a | b |`)을
`confluence_storage.py`가 **Confluence storage format(XHTML)** 으로
기계적으로 변환한 것입니다. 사용법: 메일에서 이 블록을 전체 선택해서
복사 → Confluence에서 새 페이지 만들기 → 편집기 오른쪽 위 **⋯(더보기)
메뉴 → 소스 편집기**를 열어 그대로 붙여넣기 → 서식이 적용된 페이지 완성.

**소스 편집기는 페이지 본문만 편집할 수 있고 제목은 별도 입력란입니다**
(소스에 `<h1>` 태그를 넣어도 그건 본문 안 제목일 뿐 페이지 제목이 되지
않습니다). 새 페이지 제목은 **원본 문서 제목을 그대로** 입력하면
됩니다 - 별도로 다른 제목을 제안하지 않습니다.

**원본 문서로 돌아갈 수 있는 링크**는 복사용 소스 맨 위에 실제
Confluence storage 문단(`<p><em>원본 문서: <a href="...">...</a></em></p>`)
으로 포함돼 있고, 그 바로 아래에 수정본 내용이 이어집니다 - 그래서
붙여넣으면 새로 만든 페이지 본문 맨 위에 원본 문서 링크가 나오고 바로
이어서 수정본 내용이 시작됩니다. 이 링크의 base URL은 REST API 호출에 쓰는
`CONFLUENCE_BASE_URL`과 다를 수 있어서(API 게이트웨이 주소와 사람이
브라우저로 보는 주소가 다른 환경이 흔함) `CONFLUENCE_WEB_BASE_URL`로
따로 설정합니다(비워두면 조직 기본값 `https://confluence.samsungds.net`
사용, `.env.example` 참고). 이 값은 리포트 화면의 "원본 열기 ↗" 링크에도
동일하게 적용됩니다.

LLM에게 처음부터 XHTML을 만들게 하지 않고 굳이 이렇게 변환 단계를 둔
이유: 자체 호스팅하는 모델일수록 복잡한 마크업 문법(태그를 안 닫거나
특수문자를 이스케이프 안 하는 등)을 안정적으로 못 지켜서, 조금이라도
깨지면 Confluence 소스 편집기에 붙여넣었을 때 페이지 전체가 깨집니다.
그래서 LLM은 지금처럼 단순하고 안정적인 평문만 만들게 하고, 결정적인
(항상 같은 규칙으로 동작하는) 파이썬 코드가 변환을 맡습니다. 대신 지원
범위는 기본 구조(제목/문단/목록/표/굵게/기울임/링크/인라인 코드)로
제한됩니다 - 표 병합, 이미지, Confluence 매크로 등은 지원하지 않습니다
(애초에 원본을 LLM에게 넘기기 전 평문으로 바꾸는 단계에서부터 그
정보가 빠져 있어서 복원할 수 없습니다). 붙여넣기 전에 내용을 한 번
검토하는 것을 권장합니다.

**이미지는 쓰기 API가 없어서 새 페이지로 자동으로 옮겨줄 수 없습니다**
(첨부파일은 페이지마다 따로 올려야 합니다). 대신 원본 문서를 조회할 때
첨부파일 목록(`children.attachment`)도 같이 받아와서, 본문의 이미지와
파일명이 일치하면 그 자리에 실제 다운로드 링크를 붙여줍니다 - 원본/
수정본 텍스트와 복사용 소스 양쪽 모두에서 `[파일명](다운로드 링크)`
형태로 클릭 가능한 링크로 나타나므로, 링크를 눌러 원본을 받은 뒤 새
페이지에 직접 다시 첨부하면 됩니다. 이 링크는 사내 Confluence 로그인
세션이 있어야 열립니다.

"이메일로 받기"와 "Markdown으로 다운로드"는 화면에 이미 렌더링된 결과를
그대로 재사용합니다 - Confluence를 다시 조회하거나 LLM을 다시 호출하지
않습니다(그러면 페이지당 최대 2번씩 다시 도는 LLM 호출 때문에 버튼을
누를 때마다 오래 걸립니다). `/analyze` 화면에 hidden 필드로 결과를
같이 담아뒀다가 그대로 전달하는 방식이라, 화면에 보이는 결과가 바뀌지
않는 한(같은 결과를 다시 받는 한) 버튼을 눌러도 즉시 처리됩니다.

**"CO400" 등 파라미터 오류가 뜬다면** 요청 본문/쿼리스트링 형식이 API가
기대하는 것과 다르다는 뜻입니다 - 이 앱은 JSON 문자열을 그대로 body에
담아 `Content-Type: application/json;charset=utf-8`로 보내고
(multipart/form-data로 감싸지 않습니다), 사용자 ID는 쿼리스트링에
`?userId=...`로 붙입니다(대소문자까지 정확히 "userId" - "userID"로
보내면 파라미터를 못 찾아 오류가 납니다). 그래도 사내 메일 API
문서/샘플 코드와 실제 요청 형식이 다르면 같은 오류가 재현될 수 있으니,
성공이 확인된 샘플 코드가 있다면 알려주세요 - 정확히 맞춰서 고칠 수
있습니다.

**"이메일 발송에 실패했습니다: 401 ..." 같은 오류가 뜬다면** 화면에 표시된
응답 본문을 확인하세요 - `MAIL_API_TOKEN`이 만료/오발급됐거나,
`MAIL_API_SYSTEM_ID`/`MAIL_API_USER_ID`가 토큰 발급 시 받은 값과
일치하지 않는 경우가 흔합니다. 토큰/System-ID/userId 값은 `.env`에
붙여넣을 때 앞뒤 공백이나 개행이 섞이기 쉬운데, 이 앱은 이 값들을 자동
strip해서 보내므로 그 자체는 문제가 되지 않습니다 - 그래도 401이 나면
값 자체가 잘못됐다는 뜻이니 발급받은 값을 다시 확인하세요.

**"502 Bad Gateway"가 뜬다면** 사내 프록시(`HTTP_PROXY`/`HTTPS_PROXY`)가
이 메일 API 호출을 제대로 못 넘기는 경우가 흔합니다. `.env`에
`MAIL_API_NO_PROXY=true`를 추가하면 이 메일 API 호출만 환경변수 프록시를
건너뛰고 직접 나갑니다.

> 주의: `MAIL_API_NO_PROXY=true`로 바꾼 뒤 502 대신 **"404 Not Found"**가
> 뜬다면, 반대로 이 메일 API가 프록시를 거쳐야만 접근 가능한 구조라는
> 뜻입니다(사내 프록시가 `openapi.samsung.net` 같은 도메인을 실제 내부
> 백엔드로 라우팅해주는 경우, 프록시를 건너뛰면 그 라우팅 없이 도메인에
> 직접 붙게 되어 엉뚱한(또는 존재하지 않는) 경로로 요청이 갑니다). 이 경우
> `MAIL_API_NO_PROXY`를 다시 끄고, 502는 프록시가 아닌 다른 원인(메일 API
> 서버 자체의 일시적 문제, 타임아웃 등)일 가능성을 사내 인프라팀과
> 확인하세요.

메일 API 서버가 자체 서명 인증서를 써서 TLS 검증이 실패한다면
`MAIL_API_VERIFY_SSL=false`로 끌 수 있습니다(기본값 `true`,
`CONFLUENCE_VERIFY_SSL`과 동일한 성격).

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

## AI-Friendly 문서 작성 가이드라인

사내에서 정한, AI가 이해하기 좋은 문서를 쓰기 위한 가이드라인입니다. **핵심
가이드라인 7개**는 이 도구의 점수 산정 기준이 되고, **추가 권장 가이드 7개**는
리포트에 제안으로는 나오지만 점수에는 반영되지 않습니다.

각 가이드라인은 규칙 엔진(결정론적 코드 체크)이나 LLM 심층 검토(내용 기반
판단) 중 하나 이상으로 확인됩니다. "LLM 전용"으로 표시된 항목은 `.env`에
`LLM_BASE_URL`을 설정해야만 확인할 수 있고, 설정 안 돼 있으면 리포트에
"확인 불가"로 표시됩니다 (위반으로 간주하지 않음).

### 핵심 가이드라인

| ID | 가이드라인 | 확인 방법 |
| --- | --- | --- |
| `core-1` | 대명사 사용 자제 및 주어 포함 | LLM 전용 (구조적으로는 `ambiguous-link-text` 규칙이 링크 텍스트의 모호한 지시어만 부분적으로 잡음) |
| `core-2` | 이미지/표 설명 표기 | 규칙: `missing-alt-text`, `missing-table-header` |
| `core-3` | 원본/참조 문서 경로 표기 | LLM 전용 |
| `core-4` | 사용 용어 통일 | LLM 전용 |
| `core-5` | 전문 용어 별도 정리 | LLM 전용 |
| `core-6` | 상대적 시간 표현 대신 절대 날짜 명시 | 규칙: `relative-time-expression` (+ LLM 보완) |
| `core-7` | 문서의 자체 완결성 (참조 문서 없이도 핵심 맥락 파악 가능) | LLM 전용 |

### 추가 권장 가이드

| ID | 가이드라인 | 확인 방법 |
| --- | --- | --- |
| `extra-1` | 서론/본론/결론 흐름으로 작성 | LLM 전용 |
| `extra-2` | 셀 병합/표 중첩 지양 | 규칙: `merged-or-nested-table` |
| `extra-3` | 스타일 기능 사용 (일반 텍스트로 제목/강조 흉내내지 않기) | LLM 전용 (다만 LLM에 전달하는 평문에는 스타일 정보가 빠져 있어 실제로는 판단하지 않음 - 향후 개선 여지) |
| `extra-4` | 주제가 바뀔 때 섹션 분리 | 규칙: `heading-hierarchy-skip`, `missing-h1` |
| `extra-5` | 제목만 봐도 내용 파악 가능하게 작성 | 규칙: `vague-heading` (+ LLM 보완) |
| `extra-6` | 절차성 내용은 번호 리스트로 작성 | 규칙: `pseudo-numbered-list` (+ LLM 보완) |
| `extra-7` | 과도한 매크로/위젯보다 기본 텍스트·표 구조 우선 | 규칙: `excessive-macros` |

## 핵심 가이드라인 점수화

페이지마다 핵심 가이드라인 7개 중 몇 개를 준수했는지로 점수(0~100점)를 매깁니다.

- **준수**: 해당 가이드라인을 확인할 방법(규칙 또는 LLM)이 있었고, 위반이 발견되지 않음
- **위반**: 규칙 또는 LLM이 위반 사례를 찾음
- **확인 불가**: LLM 전용 가이드라인인데 `LLM_BASE_URL`이 없거나 이번 분석에서 LLM 호출이 실패한 경우 - 점수 계산에서 제외됨 (위반으로 치지 않음)

점수 = `100 * 준수 개수 / 확인 가능 개수` (반올림). 확인 가능한 항목이 하나도
없으면(예: 규칙 위반도 없고 LLM도 꺼져 있어서 7개 다 확인 불가) 점수는 계산하지
않고 `-`로 표시합니다.

같은 문서를 여러 번 분석했는데 결과가 "준수"와 "확인 불가"를 오간다면,
LLM 호출(찾기/수정안 채우기)이 그때그때 실패하고 있다는 뜻입니다 - LLM이
설정돼 있어도 매 실행 성공을 보장하진 않기 때문입니다. 이를 줄이기 위해
찾기/수정안 채우기 호출은 (1) 규칙 위반 개수에 비례해 출력 토큰 예산을
자동으로 늘리고, (2) 실패하면 한 번 더 재시도하며, (3) temperature를 0으로
써서 같은 입력엔 최대한 같은 결과가 나오도록 합니다. 그래도 계속 실패하면
리포트에 남는 `llm-review-error` 항목의 메시지로 원인(타임아웃, 응답 잘림
등)을 확인할 수 있습니다.

## 리포트 예시 구조

```
# AI-Friendly 문서 개선 제안 리포트

| 페이지 | 제안 수 | 심각 | 경고 | 참고 | 핵심 가이드 점수 |
| --- | --- | --- | --- | --- | --- |
| 배포 가이드 | 3 | 0 | 2 | 1 | 86점 |

## 배포 가이드
- 원본: [https://your-domain.atlassian.net/wiki/spaces/ENG/pages/123456](https://your-domain.atlassian.net/wiki/spaces/ENG/pages/123456)
...

**핵심 가이드라인 준수**

점수: **86점** (6/7개 항목 준수)

| 가이드라인 | 상태 |
| --- | --- |
| 대명사 사용 자제 및 주어 포함 | ⚠️ 위반 |
| 이미지/표 설명 표기 | ✅ 준수 |
...

### [🟡 경고] '사전 준비' 섹션의 표 #1 (4행 x 3열)
- 규칙: `missing-table-header`
- 문제: 표에 헤더 행이 없어 각 열이 무엇을 의미하는지 문맥 없이는 알기 어려움
- 제안: 첫 번째 행을 헤더(th)로 지정해 각 열의 의미를 명시하세요.

**최종 수정본**

(문서 전체를 발견 사항/수정안까지 반영해 다시 쓴 최종본이 여기 들어갑니다)
```

위 예시는 LLM 미설정 상태(조언 형태)를 보여줍니다. `LLM_BASE_URL`이 설정돼
있으면 "제안" 줄이 "첫 번째 행을 헤더(th)로 지정해 각 열의 의미를
명시하세요." 같은 조언 대신, 예를 들어 `<tr><th>OS</th><th>버전</th>
<th>필수 여부</th></tr>` 처럼 문서 내용을 참고해 만든, 그대로 붙여넣을 수
있는 실제 텍스트로 나오고, "최종 수정본" 섹션에도 실제 수정본 전체가
채워집니다(수정본 생성 자체가 실패하면 실패 사유가 대신 표시됩니다).
원본 URL은 리포트/웹 UI 어디서나 클릭 가능한 링크로 나옵니다.

## 포함된 스타터 규칙

| 규칙 ID | 설명 | 가이드라인 |
| --- | --- | --- |
| `heading-hierarchy-skip` | 제목 레벨이 갑자기 건너뛰는 경우 (H1 → H3 등) | `extra-4` |
| `missing-h1` | 문서에 최상위 제목(H1)이 없는 경우 | `extra-4` |
| `missing-table-header` | 헤더 행이 없는 표 | `core-2` |
| `missing-alt-text` | 대체 텍스트가 없는 이미지 | `core-2` |
| `ambiguous-link-text` | "여기", "click here" 등 맥락 없이 이해 불가능한 링크 텍스트 | `core-1` |
| `long-paragraph` | 지나치게 긴 문단 (기본 120단어 초과) | - |
| `relative-time-expression` | "최근에", "지난주" 등 상대적 시간 표현 | `core-6` |
| `merged-or-nested-table` | 셀 병합(colspan/rowspan)이나 표 중첩 | `extra-2` |
| `vague-heading` | "설정", "기타" 등 내용을 짐작하기 어려운 제목 | `extra-5` |
| `pseudo-numbered-list` | 리스트 대신 문단 안에 번호만 나열한 절차 | `extra-6` |
| `excessive-macros` | 과도하게 많은 Confluence 매크로 사용 (기본 8개 초과) | `extra-7` |

## LLM 심층 검토 (선택)

규칙 엔진은 결정론적으로 판별 가능한 항목만 잡습니다. `.env`에
`LLM_BASE_URL`을 설정하면, 실제 문서 내용을 LLM에게 읽혀서 두 가지를 더
합니다:

1. **새 문제 찾기**: 위 가이드라인 중 "LLM 전용"으로 표시된 항목들(대명사/
   주어 생략, 참조 문서 경로, 용어 통일, 전문 용어 정리, 문서 자체 완결성,
   서론/본론/결론 흐름 등)을 확인합니다. 각 지적 사항에 관련 가이드라인
   ID를 함께 답하도록 프롬프트되어 있고, 이 값이 점수 계산에도 그대로
   쓰입니다.
2. **규칙 기반 제안을 실제 수정안으로 채우기**: 규칙 엔진은 "표에 헤더가
   없다", "alt 텍스트가 없다" 같은 문제는 찾아도, 실제로 어떤 문구를
   채워야 하는지는 모릅니다(예: 이미지 내용을 못 보고, 표 값도 모릅니다).
   LLM은 문서 전체를 읽었기 때문에, 각 규칙 위반에 대해 **문서에 그대로
   복사해서 붙여넣을 수 있는 실제 수정 텍스트**를 만들어 그 제안(`suggestion`)
   내용을 교체합니다. 확실히 알 수 없는 부분(이미지의 실제 내용, 정확한
   날짜 등)은 문서 안의 단서(이미지 파일명, 주변 문맥 등)로 최선을 다해
   추정하고 "(추정, 확인 필요)"처럼 표시하도록 프롬프트되어 있습니다.

vLLM 등 OpenAI 호환 API 엔드포인트를 그대로 쓸 수 있습니다 (`.env.example`의
LLM 관련 항목 참고). 설정돼 있으면 CLI/웹 UI 모두에서 매 분석마다 자동으로
같이 실행되며, 별도로 켜고 끄는 옵션은 없습니다. LLM 호출이 실패해도 규칙
기반 결과(원래의 조언 형태 제안)는 그대로 리포트에 남고, 실패 사실만 별도
항목(`llm-review-error`)으로 표시됩니다 (이 경우 LLM 전용 가이드라인들은
점수에서 "확인 불가"로 처리됩니다). LLM이 새로 찾은 문제는 `llm-review`
규칙 ID로 리포트에 섞여서 나타나고, 규칙 기반 제안은 원래 규칙 ID를
유지한 채 `suggestion` 내용만 구체화됩니다.

**원본 vs 수정본 나란히 보기 (웹 UI)**: `LLM_BASE_URL`이 설정돼 있으면, 위
1·2번에서 찾은 문제와 수정안을 모두 반영해 문서 전체를 다시 쓴 수정본
(`revised_document`)도 만듭니다. 웹 UI의 `/analyze` 분석 결과 화면에는
페이지별로 펼칠 수 있는 아코디언이 나오고, 각 페이지를 펼치면 원본 문서와
수정본이 나란히 표시됩니다. 여러 페이지/스페이스를 한 번에 분석해도
페이지별로 아코디언을 따로 펼쳐서 비교할 수 있습니다. `LLM_BASE_URL`이
설정 안 돼 있거나 수정본을 만들지 못한 경우에는 원본은 그대로 보여주고
수정본 자리에는 안내 문구가 대신 표시됩니다.

수정본 생성은 위 1·2번(새 문제 찾기/수정안 채우기)과 **별도의 LLM
호출**로 이루어집니다. 문서 전체를 거의 그대로 다시 써야 해서 출력이 길고
(응답 길이가 문서 길이에 비례), 자체 호스팅하는 소형 모델일수록 중간에
잘리거나 실패하기 쉽습니다. 두 호출을 분리해둔 이유가 바로 이것입니다 -
수정본 생성이 실패해도 이미 성공한 1·2번 결과(새로 찾은 문제/구체적
수정안)는 그대로 리포트에 남고, 수정본만 만들어지지 않습니다. 수정본이
안 만들어지면 **실패 사유가 안내 문구와 리포트의 "문서 전체 수정본을
만들지 못했습니다" 항목에 그대로 표시되니**, 서버 로그를 안 봐도 원인을
바로 알 수 있습니다.

`LLM_MAX_OUTPUT_TOKENS`는 **비워두는 게 기본이자 권장값**입니다. 그러면
수정본 호출의 토큰 예산이 입력 문서 길이에 맞춰 자동으로 늘어납니다(최소
4096). 값을 명시하면 "최소 이만큼은 보장"하는 하한으로만 쓰입니다 -
자동 계산값이 그보다 크면 자동 계산값이 우선하므로, 짧은 문서로
시험해보고 낮은 값(예: 4096)을 넣어뒀다가 나중에 더 긴 문서에서 다시
잘리는 일은 없습니다.

**"응답이 최대 토큰 제한으로 중간에 잘렸습니다" 오류가 뜬다면 반대로
`LLM_MAX_OUTPUT_TOKENS`를 지금보다 늘려야 합니다** (더 작게 조정하면
계속 잘립니다) - 자동 계산값으로도 부족했다는 뜻이니, 리포트에 표시된
현재 값보다 확실히 크게(예: 2배) 잡아서 `.env`에 명시해보세요.

**이 값을 무작정 크게(예: 수십만 이상) 잡는다고 더 안전해지지 않습니다**
- 모델이 실제로 처리할 수 있는 최대 컨텍스트 길이(vLLM이면
`--max-model-len` 등으로 기동 시 정해짐)보다 크게 요청하면, 대부분의
OpenAI 호환 서버는 응답을 만들다 자르는 게 아니라 **요청 자체를 즉시
거부**합니다(그러면 안내 문구에 "This model's maximum context length is
N tokens..." 같은 메시지가 뜹니다). 이 경우엔 `LLM_MAX_OUTPUT_TOKENS`를
모델의 최대 컨텍스트 길이보다 여유 있게 작은 값으로 낮추거나
`LLM_MAX_INPUT_CHARS`를 줄여서 입력+출력 합이 그 안에 들어오게 하세요.

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
  guidelines.py         # 14개 AI-friendly 가이드라인 정의 + 핵심 가이드라인 점수화
  analyzer.py           # 페이지 하나를 파싱 + 규칙(+ 설정 시 LLM) 적용 + 점수 계산
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
  test_parser.py
  test_guidelines.py
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
