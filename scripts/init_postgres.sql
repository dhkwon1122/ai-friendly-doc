-- ai-friendly-doc 전용 DB/유저를 새로 만드는 스크립트.
-- 이미 떠 있는 PostgreSQL 컨테이너 안에서 슈퍼유저(보통 postgres)로 실행한다.
--
-- 사용 예:
--   docker exec -i <postgres-container-name> psql -U postgres \
--     -v pass="'change-me'" -f - < scripts/init_postgres.sql
-- 또는 접속 후 직접 붙여넣어 실행해도 된다. 아래 'change-me'는 반드시
-- 실제 운영에서 쓸 강한 비밀번호로 바꿀 것.

CREATE USER ai_friendly_doc WITH PASSWORD 'change-me';
CREATE DATABASE ai_friendly_doc OWNER ai_friendly_doc;

-- 위 값을 그대로 썼다면 .env의 DATABASE_URL은 다음과 같은 형태가 된다:
--   DATABASE_URL=postgresql+psycopg2://ai_friendly_doc:change-me@host.docker.internal:5432/ai_friendly_doc
--
-- 테이블(users, confluence_credentials)은 앱이 처음 뜰 때 자동으로 생성되므로
-- 이 스크립트에서는 DB/유저 생성만 한다.
