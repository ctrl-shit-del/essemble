"""Auth request/response models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserRole
from app.schemas.common import Email, Password


class RegisterRequest(BaseModel):
    email: Email
    password: Password
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=20)
    # Typed as the full enum rather than a customer/organiser literal so that
    # an attempted admin self-registration reaches the service and is answered
    # 403 FORBIDDEN, not 422. It is an authorization failure, not a malformed
    # request, and it should read that way in logs.
    role: UserRole = UserRole.CUSTOMER


class LoginRequest(BaseModel):
    email: Email
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    role: UserRole
    phone: str | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
