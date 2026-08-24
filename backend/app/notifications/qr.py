"""QR payload and image.

The signature itself comes from core.security -- one HMAC implementation, used
by both booking creation and check-in verification. A raw booking reference is
deliberately not enough to check in (I8).
"""

import base64
import hmac
from io import BytesIO

import qrcode

from app.core.security import qr_signature


def build_payload(reference: str) -> str:
    """`ESB-XXXXXX.<16 hex chars>` -- what the QR image encodes."""
    return f"{reference}.{qr_signature(reference)}"


def split_payload(payload: str) -> tuple[str, str] | None:
    """(reference, signature), or None if it is not shaped like a payload."""
    if not payload or payload.count(".") != 1:
        return None
    reference, signature = payload.split(".", 1)
    if not reference or not signature:
        return None
    return reference, signature


def verify_payload(payload: str) -> str | None:
    """The reference if the signature checks out, else None.

    Constant-time compare: a timing side channel here would let someone
    brute-force a signature one character at a time.
    """
    parts = split_payload(payload)
    if parts is None:
        return None
    reference, signature = parts
    if not hmac.compare_digest(signature, qr_signature(reference)):
        return None
    return reference


def png_bytes(payload: str) -> bytes:
    image = qrcode.make(payload)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def png_base64(payload: str) -> str:
    return base64.b64encode(png_bytes(payload)).decode("ascii")
