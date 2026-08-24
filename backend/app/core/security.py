"""Password hashing and access tokens."""

import hashlib
import hmac
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.errors import unauthenticated

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(raw: str) -> str:
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _pwd.verify(raw, hashed)


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    """Return (token, expires_in_seconds).

    `sub` is the user id as a string, `role` is carried so that role checks do
    not need a database round-trip on every request. Ownership checks still do
    -- a role claim says what kind of user this is, never which rows are theirs.
    """
    expires_in = settings.jwt_expiry_hours * 3600
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise unauthenticated("Invalid or expired token.") from exc


#: Alphabet for booking references. Digits and uppercase letters only, so a
#: reference stays readable when someone reads it down a phone line.
REFERENCE_ALPHABET = string.ascii_uppercase + string.digits


def new_reference() -> str:
    """A candidate booking reference, ESB-XXXXXX."""
    body = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(6))
    return f"ESB-{body}"


def qr_signature(reference: str) -> str:
    """The signed half of a QR payload.

    A raw booking reference must not be enough to check in, so the payload
    carries an HMAC over it. Phase 4 renders `reference.signature` into a PNG;
    this is the part that has to exist at booking time.
    """
    digest = hmac.new(
        settings.qr_secret.encode("utf-8"),
        reference.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:16]
