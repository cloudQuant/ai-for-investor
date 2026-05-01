import secrets
import hashlib
from datetime import datetime, timedelta, timezone


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_email_verification_token(user_id: int) -> tuple[str, str, datetime]:
    token = generate_token()
    hashed = hash_token(token)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    return token, hashed, expires


def create_password_reset_token(user_id: int) -> tuple[str, str, datetime]:
    token = generate_token()
    hashed = hash_token(token)
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    return token, hashed, expires


def verify_token_hash(token: str, hashed: str) -> bool:
    return secrets.compare_digest(hash_token(token), hashed)
