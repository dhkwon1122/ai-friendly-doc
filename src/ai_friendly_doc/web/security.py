"""비밀번호 해시와 Confluence 토큰 암호화를 담당한다."""

from __future__ import annotations

import os

import bcrypt
from cryptography.fernet import Fernet, InvalidToken


class SecurityConfigError(RuntimeError):
    pass


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _get_fernet() -> Fernet:
    key = os.environ.get("FERNET_KEY")
    if not key:
        raise SecurityConfigError(
            "FERNET_KEY 환경변수가 설정되지 않았습니다. "
            "다음 명령으로 키를 생성해 .env에 추가하세요: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as e:
        raise SecurityConfigError(f"FERNET_KEY가 올바른 형식이 아닙니다: {e}") from e


def encrypt_token(plain_token: str) -> str:
    return _get_fernet().encrypt(plain_token.encode("utf-8")).decode("utf-8")


def decrypt_token(encrypted_token: str) -> str:
    try:
        return _get_fernet().decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise SecurityConfigError(
            "저장된 토큰을 복호화할 수 없습니다. FERNET_KEY가 변경되었을 수 있습니다."
        ) from e
