"""Authentication and role dependencies."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import forbidden, unauthenticated
from app.core.security import decode_access_token
from app.models import UserAccount, UserRole

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> UserAccount:
    if credentials is None:
        raise unauthenticated()

    payload = decode_access_token(credentials.credentials)
    subject = payload.get("sub")
    if subject is None:
        raise unauthenticated("Token carries no subject.")

    user = await session.scalar(
        select(UserAccount).where(UserAccount.id == int(subject))
    )
    if user is None:
        # Token signed for a user that no longer exists.
        raise unauthenticated("Unknown account.")
    return user


def require_role(
    *roles: UserRole,
) -> Callable[..., Coroutine[Any, Any, UserAccount]]:
    """Gate a route on role.

    Necessary but never sufficient for anything that names a resource: a role
    says what kind of user this is, not which rows belong to them. Routes that
    take an id must also run the ownership check in their service.
    """

    async def dependency(
        user: UserAccount = Depends(get_current_user),
    ) -> UserAccount:
        if user.role not in roles:
            raise forbidden(
                "This endpoint requires one of: "
                + ", ".join(role.value for role in roles)
            )
        return user

    return dependency


require_admin = require_role(UserRole.ADMIN)
require_organiser = require_role(UserRole.ORGANISER)
require_customer = require_role(UserRole.CUSTOMER)
