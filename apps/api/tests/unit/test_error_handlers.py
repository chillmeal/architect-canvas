from fastapi import APIRouter, Query
from fastapi.testclient import TestClient

from app.core.errors import AppError
from app.main import create_app


def test_request_id_header_is_returned_for_success() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health", headers={"X-Request-ID": "request-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-1"


def test_app_error_uses_stable_error_shape() -> None:
    router = APIRouter()

    @router.get("/boom")
    def boom() -> None:
        raise AppError("BOOM", "Expected failure", details={"field": "value"})

    app = create_app()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/boom", headers={"X-Request-ID": "request-2"})

    assert response.status_code == 400
    assert response.headers["X-Request-ID"] == "request-2"
    assert response.json() == {
        "error_code": "BOOM",
        "message": "Expected failure",
        "request_id": "request-2",
        "details": {"field": "value"},
    }


def test_request_validation_error_uses_stable_error_shape() -> None:
    router = APIRouter()

    @router.get("/validate")
    def validate(limit: int = Query(ge=1)) -> dict[str, int]:
        return {"limit": limit}

    app = create_app()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/validate?limit=0", headers={"X-Request-ID": "request-3"})

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "REQUEST_VALIDATION_ERROR"
    assert body["message"] == "Request validation failed"
    assert body["request_id"] == "request-3"
    assert "details" in body


def test_unhandled_error_does_not_expose_exception_details() -> None:
    router = APIRouter()

    @router.get("/unhandled")
    def unhandled() -> None:
        raise RuntimeError("secret internal detail")

    app = create_app()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/unhandled", headers={"X-Request-ID": "request-4"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "request-4"
    assert response.json() == {
        "error_code": "INTERNAL_SERVER_ERROR",
        "message": "Internal server error",
        "request_id": "request-4",
    }
    assert "secret internal detail" not in response.text
