"""Error envelope and the single exception path that produces it.

Every failure leaves the API as:

    {"error": {"code": ..., "message": ..., "details": ...}}

including request validation, which FastAPI would otherwise render in its own
422 shape.
"""

from __future__ import annotations

import logging
import uuid
from enum import Enum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("essemble.errors")


class ErrorCode(str, Enum):
    # booking engine (Phase 3)
    SEAT_UNAVAILABLE = "SEAT_UNAVAILABLE"
    HOLD_EXPIRED = "HOLD_EXPIRED"
    HOLD_LIMIT_EXCEEDED = "HOLD_LIMIT_EXCEEDED"
    OFFER_EXPIRED = "OFFER_EXPIRED"
    NOT_SOLD_OUT = "NOT_SOLD_OUT"
    # check-in (Phase 4)
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    ALREADY_USED = "ALREADY_USED"
    # cross-cutting
    FORBIDDEN = "FORBIDDEN"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """An error with a code the client is expected to branch on."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details

    def envelope(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "details": self.details,
            }
        }


def forbidden(message: str = "You do not have access to this resource.") -> AppError:
    """403 for both "not yours" and "does not exist".

    Deliberately identical in both cases: answering 404 for an unknown id and
    403 for someone else's turns the id space into an enumeration oracle.
    """
    return AppError(ErrorCode.FORBIDDEN, message, status.HTTP_403_FORBIDDEN)


def not_found(message: str = "Not found.") -> AppError:
    """404 for public catalog reads, where existence is not a secret."""
    return AppError(ErrorCode.NOT_FOUND, message, status.HTTP_404_NOT_FOUND)


def validation_error(message: str, details: Any = None) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        message,
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        details,
    )


def conflict(message: str, details: Any = None) -> AppError:
    return AppError(ErrorCode.CONFLICT, message, status.HTTP_409_CONFLICT, details)


def unauthenticated(message: str = "Authentication required.") -> AppError:
    return AppError(
        ErrorCode.UNAUTHENTICATED, message, status.HTTP_401_UNAUTHORIZED
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.envelope())

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(p) for p in err.get("loc", ())[1:]),
                "message": err.get("msg", ""),
            }
            for err in exc.errors()
        ]
        error = validation_error("Request validation failed.", details)
        return JSONResponse(status_code=error.status_code, content=error.envelope())

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Last resort.

        The client gets a correlation id and nothing else: a traceback or a
        driver message would leak schema, queries, and sometimes data. The
        full detail goes to the log under the same id.
        """
        correlation_id = uuid.uuid4().hex[:12]
        logger.exception(
            "unhandled error %s on %s %s",
            correlation_id,
            request.method,
            request.url.path,
        )
        error = AppError(
            ErrorCode.INTERNAL_ERROR,
            "Something went wrong on our side.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            {"correlation_id": correlation_id},
        )
        return JSONResponse(status_code=error.status_code, content=error.envelope())

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHENTICATED,
            status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
            status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
            status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
        }.get(exc.status_code, ErrorCode.VALIDATION_ERROR)
        error = AppError(code, str(exc.detail), exc.status_code)
        return JSONResponse(status_code=error.status_code, content=error.envelope())
