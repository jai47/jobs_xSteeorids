"""FastAPI dependencies, auth helpers, and exception handlers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Annotated, Any, Generator

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from config import settings
from db.engine import SessionLocal
from db.models import User

TOKEN_TTL_SECONDS = 7 * 24 * 3600
_bearer = HTTPBearer(auto_error=False)


class APIError(HTTPException):
    """HTTP exception with a stable error code for clients."""

    def __init__(
        self,
        status_code: int,
        error: str,
        code: str,
        detail: str | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(status_code=status_code, detail=error)
        self.error = error
        self.code = code
        self.extra_detail = detail
        self.extra_fields = extra


class LLMError(Exception):
    """Raised when all LLM providers fail."""


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped database session."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_session_token(user_id: uuid.UUID, email: str) -> str:
    """Create an HMAC-signed session token."""
    now = int(time.time())
    payload = {
        "user_id": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    signature = hmac.new(
        settings.dashboard_secret.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def decode_session_token(token: str) -> dict[str, Any]:
    """Validate and decode a session token."""
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError as exc:
        raise APIError(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid session token",
            "AUTH_REQUIRED",
        ) from exc

    expected = hmac.new(
        settings.dashboard_secret.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise APIError(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid session token",
            "AUTH_REQUIRED",
        )

    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()))
    except (json.JSONDecodeError, ValueError) as exc:
        raise APIError(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid session token",
            "AUTH_REQUIRED",
        ) from exc

    if int(payload.get("exp", 0)) < int(time.time()):
        raise APIError(
            status.HTTP_401_UNAUTHORIZED,
            "Session token expired",
            "AUTH_REQUIRED",
        )
    return payload


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resolve the authenticated user from the Authorization header."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIError(
            status.HTTP_401_UNAUTHORIZED,
            "Authentication required",
            "AUTH_REQUIRED",
        )

    payload = decode_session_token(credentials.credentials)
    try:
        user_id = uuid.UUID(str(payload["user_id"]))
    except (KeyError, ValueError) as exc:
        raise APIError(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid session token",
            "AUTH_REQUIRED",
        ) from exc

    user = db.get(User, user_id)
    if user is None:
        raise APIError(
            status.HTTP_401_UNAUTHORIZED,
            "User not found",
            "AUTH_REQUIRED",
        )
    return user


def _error_body(error: str, code: str, detail: str | None = None) -> dict[str, str | None]:
    return {"error": error, "code": code, "detail": detail}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach consistent JSON error handlers."""

    @app.exception_handler(APIError)
    async def api_error_handler(_request: Request, exc: APIError) -> JSONResponse:
        content = _error_body(exc.error, exc.code, exc.extra_detail)
        content.update(exc.extra_fields)
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_body("Request validation failed", "VALIDATION_ERROR", str(exc.errors())),
        )

    @app.exception_handler(LLMError)
    async def llm_error_handler(_request: Request, exc: LLMError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=_error_body(str(exc), "LLM_ERROR"),
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        detail = None if settings.is_production else str(exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body("Internal server error", "INTERNAL_ERROR", detail),
        )
