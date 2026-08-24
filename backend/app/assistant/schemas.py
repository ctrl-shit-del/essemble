"""Request and response models for the assistant."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    """One prior turn. The CLIENT holds the history and sends it back.

    Deliberately stateless on the server: no conversation table, no session
    store, nothing to expire or leak. The cost is bandwidth per request, which
    at ten turns of text is nothing.
    """

    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation: list[ChatTurn] = Field(default_factory=list, max_length=40)


class ShowOption(BaseModel):
    """A show the customer can tap to enter the seat map."""

    kind: Literal["show"] = "show"
    show_id: int
    title: str
    venue: str
    city: str | None = None
    screen: str
    starts_at: str
    language: str
    format: str | None = None
    from_price: str | None = None
    seats_available: int


class SeatOption(BaseModel):
    """A candidate seat group.

    `seat_ids` is what the frontend pre-selects on the seat map. It is a
    SELECTION, not a hold -- nothing is reserved until the customer presses
    the hold button themselves.
    """

    kind: Literal["seats"] = "seats"
    show_id: int
    seat_ids: list[int]
    seats: list[str]
    row: str
    category: str
    category_id: int
    price_per_seat: str
    total: str
    reason: str
    score_breakdown: dict[str, Any]


class ChatResponse(BaseModel):
    reply: str
    options: list[ShowOption | SeatOption] = Field(default_factory=list)
    #: Which tools ran, so the interface can say so. Transparency about what
    #: the system actually did, rather than presenting it as magic.
    tool_calls_made: list[str] = Field(default_factory=list)
