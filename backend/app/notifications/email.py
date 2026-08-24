"""Email rendering and delivery.

Two drivers, chosen by MAIL_DRIVER:

  console (default) -- render and print, including the QR payload string and
                       any claim link. The app must run end to end with no
                       credentials at all: a reviewer cloning the repo has
                       none, and a demo should not be gated on a mail account.
  resend            -- deliver through the Resend API.

Nothing here is ever called from a request. The outbox dispatcher is the only
caller (I7).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import settings
from app.notifications import qr

logger = logging.getLogger("essemble.email")

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)

SUBJECTS = {
    "booking_confirmation": "Your tickets for {event_title}",
    "waitlist_offer": "Seats are available for {event_title}",
    "booking_cancelled": "Booking {reference} cancelled",
}

HEADINGS = {
    "booking_confirmation": "Booking confirmed",
    "waitlist_offer": "Your seats are ready",
    "booking_cancelled": "Booking cancelled",
}

QR_CID = "essemble-qr"


@dataclass
class RenderedEmail:
    subject: str
    html: str
    to_email: str
    #: Inline attachment for the confirmation QR, referenced as cid:QR_CID.
    inline_images: dict[str, bytes] = field(default_factory=dict)
    qr_payload: str | None = None


def _pretty_time(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.strftime("%a %d %b %Y, %H:%M")
    return str(value)


def render(template: str, to_email: str, payload: dict[str, Any]) -> RenderedEmail:
    context = dict(payload)
    for key in ("starts_at", "expires_at"):
        if key in context:
            context[key] = _pretty_time(context[key])
    context["heading"] = HEADINGS.get(template, "Essemble")

    inline: dict[str, bytes] = {}
    qr_payload: str | None = None
    if template == "booking_confirmation":
        qr_payload = qr.build_payload(payload["reference"])
        context["qr_payload"] = qr_payload
        context["qr_cid"] = QR_CID
        inline[QR_CID] = qr.png_bytes(qr_payload)

    html = _env.get_template(f"{template}.html").render(**context)
    subject = SUBJECTS.get(template, "Essemble").format(**{
        "event_title": payload.get("event_title", ""),
        "reference": payload.get("reference", ""),
    })
    return RenderedEmail(
        subject=subject,
        html=html,
        to_email=to_email,
        inline_images=inline,
        qr_payload=qr_payload,
    )


class ConsoleDriver:
    """Print the email. Deliberately shows the QR payload and any claim link,
    so the whole flow is demonstrable without a mail account."""

    name = "console"

    def send(self, email: RenderedEmail, payload: dict[str, Any]) -> None:
        lines = [
            "",
            "=" * 68,
            f"  TO      : {email.to_email}",
            f"  SUBJECT : {email.subject}",
        ]
        if email.qr_payload:
            lines.append(f"  QR      : {email.qr_payload}")
        if payload.get("claim_url"):
            lines.append(f"  CLAIM   : {payload['claim_url']}")
        if email.inline_images:
            size = sum(len(v) for v in email.inline_images.values())
            lines.append(f"  INLINE  : {len(email.inline_images)} image, {size} bytes")
        lines += ["-" * 68, email.html.strip(), "=" * 68, ""]
        print("\n".join(lines), flush=True)


class ResendDriver:
    name = "resend"

    def send(self, email: RenderedEmail, payload: dict[str, Any]) -> None:
        import resend

        if not settings.resend_api_key:
            raise RuntimeError("MAIL_DRIVER=resend but RESEND_API_KEY is unset")
        resend.api_key = settings.resend_api_key

        body: dict[str, Any] = {
            "from": settings.mail_from,
            "to": [email.to_email],
            "subject": email.subject,
            "html": email.html,
        }
        if email.inline_images:
            import base64

            body["attachments"] = [
                {
                    "filename": f"{cid}.png",
                    "content": base64.b64encode(data).decode("ascii"),
                    "content_id": cid,
                }
                for cid, data in email.inline_images.items()
            ]
        resend.Emails.send(body)


def get_driver():
    return ResendDriver() if settings.mail_driver == "resend" else ConsoleDriver()


def deliver(template: str, to_email: str, payload: dict[str, Any]) -> None:
    """Render and send. Raises on failure so the dispatcher can retry."""
    email = render(template, to_email, payload)
    get_driver().send(email, payload)
    logger.info("sent %s to %s", template, to_email)
