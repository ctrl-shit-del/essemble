"""QR payload and image.

The signature itself comes from core.security -- one HMAC implementation, used
by both booking creation and check-in verification. A raw booking reference is
deliberately not enough to check in (I8).
"""

import base64
import hmac
from io import BytesIO
from urllib.parse import urlsplit

import qrcode

from app.core.config import settings
from app.core.security import qr_signature


def credential(reference: str) -> str:
    """`ESB-XXXXXX.<16 hex chars>` -- the signed half, on its own.

    This is the thing that is actually verified. It is separated from the URL
    that carries it because the two have different jobs: this one must stay
    byte-stable forever (old tickets keep working), while the URL around it is
    a deployment detail that can move.
    """
    return f"{reference}.{qr_signature(reference)}"


def build_payload(reference: str) -> str:
    """What the QR image encodes: a URL to the check-in page.

    Plain text was scannable but useless -- a phone camera would read
    `ESB-XXXXXX.abc123`, find nothing actionable in it, and offer the user a
    web search. Encoding a URL means the camera offers to open it, and it
    lands on a page that can actually admit someone.

    APP_BASE_URL is the frontend origin, so this resolves to a real route.
    The trailing slash is stripped because a configured value ending in "/"
    would otherwise produce a double slash in the path.
    """
    base = settings.app_base_url.rstrip("/")
    return f"{base}/checkin/{credential(reference)}"


def _extract_credential(payload: str) -> str:
    """The signed credential, from either form the scanner might send.

    A scanner reading the QR posts the whole URL; a ticket issued before this
    change carries the bare credential; someone typing at the door might send
    either. All three are the same claim, so they are normalised here rather
    than branched on downstream -- verification stays a single path.

    Only inputs that genuinely parse as an absolute URL are unwrapped. A bare
    credential has no scheme and is returned untouched, so the two forms
    cannot be confused with one another.
    """
    parsed = urlsplit(payload.strip())
    if parsed.scheme and parsed.netloc:
        return parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return payload.strip()


def split_payload(payload: str) -> tuple[str, str] | None:
    """(reference, signature), or None if it is not shaped like a payload."""
    if not payload:
        return None
    candidate = _extract_credential(payload)
    if candidate.count(".") != 1:
        return None
    reference, signature = candidate.split(".", 1)
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
