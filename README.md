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

계정 ID(`CONFLUENCE_EMAIL`) + 비밀번호(`CONFLUENCE_API_TOKEN`)로 HTTP Basic
Auth만 지원합니다 (API 토큰/Personal Access Token 인증은 지원하지 않습니다
- 사내 환경에서 토큰 방식 접근이 막혀 있는 경우가 있어 뺐습니다). 계정 ID는
이메일 형식이 아니어도 됩니다(예: 사내 로그인 ID).

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
2. `/settings`에서 본인의 Confluence 계정 ID + 비밀번호만 입력 → 값은
   `FERNET_KEY`로 암호화되어 DB에 저장. API 토큰/PAT 인증은 지원하지
   않습니다(위 참고). Confluence Base URL은 입력할 필요가 없습니다(위 참고).
3. `/analyze`에서 페이지 ID(들) 또는 스페이스 키를 입력해 분석 실행 →
   결과는 화면에 바로 렌더링되고, "Markdown으로 다운로드" 버튼으로 파일도
   받을 수 있고, 이메일 주소를 입력해 "이메일로 받기"로 리포트를 메일로도
   받을 수 있습니다(메일 API 설정 필요, 아래 참고). 각 페이지 섹션에는
   원본 Confluence 페이지로 바로 이동할 수 있는 링크가 포함됩니다.
   Write API는 여전히 호출하지 않으므로 원본 문서는 변경되지 않습니다.

CLI와 마찬가지로 사용자별 토큰은 조회에만 쓰이며, 각 사용자는 본인이 저장한
토큰으로만 조회가 가능합니다(다른 사용자의 토큰에 접근할 방법 없음).

> 운영 배포 시에는 HTTPS 뒤에 두는 것을 권장합니다(세션 쿠키/토큰 입력이
> 평문 HTTP로 오가지 않도록).

### 이메일로 리포트 받기 (선택)

SMTP가 아니라 사내 메일 발송 REST API(기본값 `openapi.samsung.net`)를
씁니다. `.env`에 `MAIL_API_TOKEN` / `MAIL_API_SYSTEM_ID` / `MAIL_API_USER_ID`
를 설정하면 `/analyze` 결과 화면에 "이메일로 받기" 입력창/버튼이
나옵니다. 입력한 주소로 분석 리포트(요약 표, 페이지별 가이드라인 점수,
발견된 문제/수정안, 최종 수정본까지 전부)를 HTML 형식으로 그대로
보냅니다 - 웹 UI에 렌더링되는 내용과 동일합니다. 셋 중 하나라도 없으면
버튼을 눌러도 설정이 안 됐다는 안내가 뜹니다. 자세한 환경변수는
`.env.example`을 참고하세요.

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
