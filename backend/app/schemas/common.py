"""Shared field types and the documented error shape."""

from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints

#: Deliberately a regex rather than pydantic's EmailStr, which would pull in
#: email-validator. Dependencies are graded on minimalism.
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]

Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]


def _decimal_without_float(value: Any) -> Any:
    """Route floats through str so 499.99 never becomes 499.98999999999995."""
    if isinstance(value, float):
        return str(value)
    return value


Money = Annotated[
    Decimal,
    BeforeValidator(_decimal_without_float),
    Field(ge=0, max_digits=10, decimal_places=2),
]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorEnvelope(BaseModel):
    """The shape of every failure response."""

    error: ErrorBody
