"""Auth routes."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.identity import service
from app.identity.deps import get_current_user
from app.models import UserAccount
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a customer or organiser",
)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Create an account and return an access token.

    Errors:
      * `FORBIDDEN` (403) -- role='admin'; admin accounts are seeded only.
      * `VALIDATION_ERROR` (422) -- email already registered, or bad input.
    """
    return await service.register(session, payload)


@router.post("/login", response_model=TokenResponse, summary="Exchange credentials")
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Errors:
      * `UNAUTHENTICATED` (401) -- unknown email or wrong password.
    """
    return await service.login(session, payload)


@router.get("/me", response_model=UserResponse, summary="The calling account")
async def me(user: UserAccount = Depends(get_current_user)) -> UserResponse:
    """Errors:
      * `UNAUTHENTICATED` (401) -- missing, malformed or expired token.
    """
    return UserResponse.model_validate(user)
