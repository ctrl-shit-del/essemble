"""Assistant HTTP surface."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import service
from app.assistant.schemas import ChatRequest, ChatResponse
from app.core.db import get_session
from app.identity.deps import require_customer
from app.models import UserAccount

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.post("/chat", response_model=ChatResponse, summary="Ask the booking assistant")
async def chat(
    payload: ChatRequest,
    user: UserAccount = Depends(require_customer),
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    """Resolve a request into ranked options.

    The assistant is READ-ONLY. It searches and ranks; it cannot hold,
    confirm, cancel, join a waitlist or claim an offer, and there is no tool
    that would let it. The customer taps a returned option and enters the
    ordinary booking flow, unchanged.

    The caller's identity comes from the token, never from the body -- the
    model has no way to ask about another customer's history.

    Errors:
      * `INTERNAL_ERROR` (503) -- no GROQ_API_KEY configured on this
        deployment, or the upstream model is unreachable.
      * `CONFLICT` (429) -- hourly message limit reached;
        `details.retry_after_seconds` says when to come back.
      * `FORBIDDEN` (403) -- the assistant is for customers.
    """
    service.check_rate_limit(user.id)
    return await service.chat(session, payload, user_id=user.id)
