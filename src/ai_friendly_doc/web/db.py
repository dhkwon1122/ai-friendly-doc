"""사용자 계정 및 사용자별 Confluence 인증 정보를 저장하는 아주 단순한 SQLite 레이어.

민감 정보(비밀번호, Confluence API 토큰)는 절대 평문으로 저장하지 않는다.
비밀번호는 bcrypt 해시, 토큰은 Fernet 대칭키로 암호화해서 저장한다.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

DB_PATH = os.environ.get("AI_FRIENDLY_DOC_DB", "ai_friendly_doc.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS confluence_credentials (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    base_url TEXT NOT NULL,
    auth_type TEXT NOT NULL,
    email TEXT,
    encrypted_token TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


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


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(_SCHEMA)


def create_user(username: str, password_hash: str) -> User:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, datetime.now(timezone.utc).isoformat()),
        )
        return User(id=cur.lastrowid, username=username, password_hash=password_hash)


def get_user_by_username(username: str) -> User | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return User(**dict(row)) if row else None


def get_user_by_id(user_id: int) -> User | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return User(**dict(row)) if row else None


def save_credentials(
    user_id: int,
    base_url: str,
    auth_type: str,
    email: str | None,
    encrypted_token: str,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO confluence_credentials (user_id, base_url, auth_type, email, encrypted_token, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                base_url = excluded.base_url,
                auth_type = excluded.auth_type,
                email = excluded.email,
                encrypted_token = excluded.encrypted_token,
                updated_at = excluded.updated_at
            """,
            (user_id, base_url, auth_type, email, encrypted_token, datetime.now(timezone.utc).isoformat()),
        )


def get_credentials(user_id: int) -> StoredCredentials | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT base_url, auth_type, email, encrypted_token FROM confluence_credentials WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return StoredCredentials(**dict(row)) if row else None
