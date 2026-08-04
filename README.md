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
- **Confluence Server/Data Center**: `CONFLUENCE_AUTH_TYPE=bearer` +
  Personal Access Token(`CONFLUENCE_API_TOKEN`).

`CONFLUENCE_BASE_URL`은 Cloud 기준 `https://<domain>.atlassian.net/wiki` 형태입니다.

## 사용법

특정 페이지 ID 분석:

```bash
ai-friendly-doc --page-id 123456 --page-id 234567 -o report.md
```

스페이스 전체 분석:

```bash
ai-friendly-doc --space-key ENG -o report.md
```

`-o`를 생략하면 표준출력으로 리포트가 출력됩니다.

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

## 새 규칙 추가하기

`src/ai_friendly_doc/rules/base.py`의 `Rule`을 상속해 `check(doc: ParsedDoc)`을
구현하고, `src/ai_friendly_doc/rules/__init__.py`의 `DEFAULT_RULES`에 등록하면
됩니다. `ParsedDoc`은 문서의 제목/표/이미지/링크/문단을 순서대로 담고 있습니다
(`src/ai_friendly_doc/parser.py` 참고).

내용 자체를 다루는 규칙(모호한 표현 감지, 사내 은어 풀이, LLM 재작성 제안 등)은
아직 정리 중이며, 규칙이 확정되는 대로 이 스타터 세트에 추가할 예정입니다.

## 테스트

```bash
pytest
```

## 프로젝트 구조

```
src/ai_friendly_doc/
  config.py             # .env 기반 설정 로더
  confluence_client.py  # Confluence REST API 읽기 전용 클라이언트
  parser.py             # storage format(XHTML) -> ParsedDoc 변환
  analyzer.py           # 페이지 하나를 파싱 + 규칙 적용
  report.py             # 제안 목록 -> Markdown 리포트
  cli.py                # CLI 진입점
  rules/
    base.py             # Rule / Suggestion 기본 클래스
    starter.py           # 스타터 규칙 구현
tests/
  test_rules.py
```
