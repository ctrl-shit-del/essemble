"""Async engine, session factory and the FastAPI session dependency.

One engine per process. Sessions are request-scoped: the dependency opens a
session, hands it to the route, and closes it afterwards. Services are
responsible for committing -- the dependency deliberately does not auto-commit,
because the booking engine relies on precise transaction boundaries.
"""

from collections.abc import AsyncIterator

from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

_pool_options: dict = (
    {"poolclass": NullPool}
    if settings.db_use_null_pool
    else {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_pre_ping": True,
        # Free-tier hosts drop idle connections; recycle before they do.
        "pool_recycle": 1800,
    }
)

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    **_pool_options,
)

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped AsyncSession."""
    async with SessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
