"""Secure primitives; not an E2EE implementation."""
from __future__ import annotations
import hashlib
import hmac
import secrets
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16, type=Type.ID)
MIN_PASSWORD_LENGTH = 14
MAX_PASSWORD_LENGTH = 1024


def validate_owner_password(password: str) -> None:
    if not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
        raise ValueError("A palavra-passe do proprietário deve ter 14 a 1024 caracteres.")


def hash_password(password: str) -> str:
    validate_owner_password(password)
    return PASSWORD_HASHER.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError, ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def token_matches(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided.encode(), expected.encode())
