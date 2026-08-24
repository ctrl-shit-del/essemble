"""Replay ledger for unsafe POSTs.

One implementation, used by POST /api/holds and POST /api/holds/{id}/confirm.
Deliberately NOT applied to offer claim: that token is single-use by
construction, so a second attempt is meant to fail rather than replay.

The ledger row is written inside the same transaction as the effect it
describes. A client retry therefore finds either the effect and its response
together, or neither -- it can never produce a second hold, and a rolled-back
operation leaves no key behind to replay later.
"""

import hashlib
import json
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import conflict
from app.models import IdempotencyKey

HEADER = "Idempotency-Key"

#: ON CONFLICT DO NOTHING: a concurrent duplicate loses the insert rather than
#: erroring, and is then answered from the winner's stored response.
INSERT_KEY = text(
    """
    INSERT INTO idempotency_key
        (key, user_id, endpoint, request_fingerprint, response_body, status_code)
    VALUES (:key, :user_id, :endpoint, :fingerprint,
            CAST(:response_body AS jsonb), :status_code)
    ON CONFLICT (key, user_id) DO NOTHING
    RETURNING key
    """
)


def fingerprint(body: bytes) -> str:
    """Stable hash of the request body, so a retry can be told from a reuse."""
    if not body:
        return hashlib.sha256(b"").hexdigest()
    try:
        # Normalise key order, so a semantically identical retry matches.
        normalised = json.dumps(json.loads(body), sort_keys=True, separators=(",", ":"))
    except ValueError:
        normalised = body.decode("utf-8", "replace")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


class Idempotency:
    """Per-request handle. `key` is None when the client did not send one."""

    def __init__(self, session: AsyncSession, key: str | None, body: bytes) -> None:
        self._session = session
        self.key = key
        self.fingerprint = fingerprint(body) if key else None

    async def replay(
        self, user_id: int, endpoint: str
    ) -> JSONResponse | None:
        """The stored response, if this exact request has been seen."""
        if not self.key:
            return None

        row = await self._session.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.key == self.key,
                IdempotencyKey.user_id == user_id,
            )
        )
        if row is None:
            return None

        # Same key, different operation: replaying would hand back a response
        # describing something the client did not ask for.
        if row.endpoint != endpoint:
            raise conflict(
                "That Idempotency-Key was already used for a different request.",
                {"endpoint": row.endpoint},
            )
        if (
            row.request_fingerprint is not None
            and row.request_fingerprint != self.fingerprint
        ):
            raise conflict(
                "That Idempotency-Key was already used with a different body."
            )

        return JSONResponse(content=row.response_body or {}, status_code=row.status_code)

    async def commit_with(
        self,
        user_id: int,
        endpoint: str,
        body: dict[str, Any],
        status_code: int,
    ) -> JSONResponse:
        """Persist the ledger row and the operation together, then respond."""
        if self.key:
            won = await self._session.scalar(
                INSERT_KEY,
                {
                    "key": self.key,
                    "user_id": user_id,
                    "endpoint": endpoint,
                    "fingerprint": self.fingerprint,
                    "response_body": json.dumps(body),
                    "status_code": status_code,
                },
            )
            if won is None:
                # A concurrent request with the same key committed first.
                # Discard this one's work and answer with the winner's result.
                await self._session.rollback()
                replayed = await self.replay(user_id, endpoint)
                if replayed is not None:
                    return replayed

        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            replayed = await self.replay(user_id, endpoint)
            if replayed is None:
                raise
            return replayed

        return JSONResponse(content=body, status_code=status_code)


async def get_idempotency(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Idempotency:
    """FastAPI dependency. Reading the body here is safe: FastAPI caches it."""
    return Idempotency(session, request.headers.get(HEADER), await request.body())
