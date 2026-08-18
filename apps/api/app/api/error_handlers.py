from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import ConfigError
from app.core.errors import AppError
from app.core.logging import get_request_id

REQUEST_ID_HEADER = "X-Request-ID"


def register_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        request.state.request_id = request_id
        token = get_request_id().set(request_id)
        try:
            response = await call_next(request)
        except Exception:
            get_request_id().reset(token)
            raise
        finally:
            if get_request_id().get() == request_id:
                get_request_id().reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(ConfigError)
    async def config_error_handler(request: Request, exc: ConfigError) -> JSONResponse:
        return _error_response(
            request,
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code="CONFIG_INVALID",
            message="Application configuration is invalid",
            details={"errors": exc.errors},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            request,
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            error_code="REQUEST_VALIDATION_ERROR",
            message="Request validation failed",
            details={"errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request.app.state.logger.exception(
            "Unhandled request error",
            extra={"error_code": "INTERNAL_SERVER_ERROR"},
            exc_info=exc,
        )
        return _error_response(
            request,
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code="INTERNAL_SERVER_ERROR",
            message="Internal server error",
        )


def _error_response(
    request: Request,
    *,
    status_code: int,
    error_code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    body: dict[str, object] = {
        "error_code": error_code,
        "message": message,
        "request_id": request_id,
    }
    if details is not None:
        body["details"] = details
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers={REQUEST_ID_HEADER: request_id} if request_id else None,
    )
