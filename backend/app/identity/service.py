"""Identity business logic."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import forbidden, unauthenticated, validation_error
from app.core.security import create_access_token, hash_password, verify_password
from app.models import UserAccount, UserRole
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse

#: Roles a stranger may create for themselves. Admins are seeded.
SELF_SERVICE_ROLES = (UserRole.CUSTOMER, UserRole.ORGANISER)


async def register(session: AsyncSession, payload: RegisterRequest) -> TokenResponse:
    if payload.role not in SELF_SERVICE_ROLES:
        # Admins own venues, screens, layouts and the venue-request queue.
        # Letting anyone mint one would hand out venue infrastructure
        # authority to a stranger with a POST body.
        raise forbidden("Admin accounts cannot be self-registered.")

    existing = await session.scalar(
        select(UserAccount.id).where(UserAccount.email == payload.email)
    )
    if existing is not None:
        raise validation_error(
            "That email is already registered.", [{"field": "email"}]
        )

    user = UserAccount(
        email=payload.email,
        password_hash=hash_password(payload.password),
        name=payload.name,
        phone=payload.phone,
        role=payload.role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _token_for(user)


async def login(session: AsyncSession, payload: LoginRequest) -> TokenResponse:
    user = await session.scalar(
        select(UserAccount).where(UserAccount.email == payload.email)
    )
    # Same answer for unknown email and wrong password: which of the two it
    # was is not the caller's business.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise unauthenticated("Incorrect email or password.")
    return _token_for(user)


def _token_for(user: UserAccount) -> TokenResponse:
    token, expires_in = create_access_token(user.id, user.role.value)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )
