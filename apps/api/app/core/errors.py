from http import HTTPStatus
from typing import Any


class AppError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        status_code: int = HTTPStatus.BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)
