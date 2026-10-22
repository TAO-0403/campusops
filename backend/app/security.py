import hashlib
import hmac
import secrets

from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded_password: str) -> bool:
    try:
        return password_hash.verify(password, encoded_password)
    except Exception:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(expected: str, supplied: str | None) -> bool:
    return supplied is not None and hmac.compare_digest(expected, supplied)
