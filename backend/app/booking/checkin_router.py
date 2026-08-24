"""Door check-in route."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.booking import checkin
from app.core.db import get_session
from app.identity.deps import require_admin
from app.models import UserAccount

router = APIRouter(prefix="/api/checkin", tags=["checkin"])


@router.post(
    "/verify",
    response_model=checkin.CheckinResponse,
    summary="Verify and consume a ticket QR",
)
async def verify(
    payload: checkin.CheckinRequest,
    admin: UserAccount = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> checkin.CheckinResponse:
    """Admit a booking once.

    Admin role is necessary but not sufficient: the admin must own the venue
    whose screen the show runs on.

    Errors:
      * `INVALID_SIGNATURE` (400) -- malformed payload or bad HMAC.
      * `FORBIDDEN` (403) -- not your venue, or the booking is not confirmed.
      * `ALREADY_USED` (409) -- `details.checked_in_at` carries the original
        admission time.
    """
    return await checkin.verify(session, admin, payload.qr_payload)
