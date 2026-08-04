"""사용자 계정 및 사용자별 Confluence 인증 정보를 저장하는 저장소.

민감 정보(비밀번호, Confluence API 토큰)는 절대 평문으로 저장하지 않는다.
비밀번호는 bcrypt 해시, 토큰은 Fernet 대칭키로 암호화해서 저장한다.

DATABASE_URL 환경변수로 백엔드를 고른다.
  - 서버/운영: postgresql+psycopg2://user:pass@host:5432/dbname
  - 로컬 개발(기본값): sqlite:///ai_friendly_doc.db
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    select,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Engine


def _default_database_url() -> str:
    sqlite_path = os.environ.get("AI_FRIENDLY_DOC_DB", "ai_friendly_doc.db")
    return f"sqlite:///{sqlite_path}"


DATABASE_URL = os.environ.get("DATABASE_URL") or _default_database_url()

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String, unique=True, nullable=False),
    Column("password_hash", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

confluence_credentials = Table(
    "confluence_credentials",
    metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("base_url", String, nullable=False),
    Column("auth_type", String, nullable=False),
    Column("email", String),
    Column("encrypted_token", String, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True)
class User:
    id: int
    username: str
    password_hash: str


@dataclass(frozen=True)
class StoredCredentials:
    base_url: str
    auth_type: str
    email: str | None
    encrypted_token: str


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
    return _engine


def init_db() -> None:
    metadata.create_all(get_engine())


def _upsert(table: Table):
    if get_engine().dialect.name == "postgresql":
        return postgresql.insert(table)
    return sqlite.insert(table)


def create_user(username: str, password_hash: str) -> User:
    created_at = datetime.now(timezone.utc)
    with get_engine().begin() as conn:
        result = conn.execute(
            users.insert().values(username=username, password_hash=password_hash, created_at=created_at)
        )
        user_id = result.inserted_primary_key[0]
    return User(id=user_id, username=username, password_hash=password_hash)


def get_user_by_username(username: str) -> User | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(users.c.id, users.c.username, users.c.password_hash).where(users.c.username == username)
        ).mappings().first()
        return User(**row) if row else None


def get_user_by_id(user_id: int) -> User | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(users.c.id, users.c.username, users.c.password_hash).where(users.c.id == user_id)
        ).mappings().first()
        return User(**row) if row else None


def save_credentials(
    user_id: int,
    base_url: str,
    auth_type: str,
    email: str | None,
    encrypted_token: str,
) -> None:
    updated_at = datetime.now(timezone.utc)
    stmt = _upsert(confluence_credentials).values(
        user_id=user_id,
        base_url=base_url,
        auth_type=auth_type,
        email=email,
        encrypted_token=encrypted_token,
        updated_at=updated_at,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[confluence_credentials.c.user_id],
        set_={
            "base_url": stmt.excluded.base_url,
            "auth_type": stmt.excluded.auth_type,
            "email": stmt.excluded.email,
            "encrypted_token": stmt.excluded.encrypted_token,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    with get_engine().begin() as conn:
        conn.execute(stmt)


def get_credentials(user_id: int) -> StoredCredentials | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(
                confluence_credentials.c.base_url,
                confluence_credentials.c.auth_type,
                confluence_credentials.c.email,
                confluence_credentials.c.encrypted_token,
            ).where(confluence_credentials.c.user_id == user_id)
        ).mappings().first()
        return StoredCredentials(**row) if row else None
