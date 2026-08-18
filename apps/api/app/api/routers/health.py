from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import get_app_config
from app.core.config import AppConfig

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app_env: str


@router.get("/health", response_model=HealthResponse)
def get_health(config: Annotated[AppConfig, Depends(get_app_config)]) -> HealthResponse:
    return HealthResponse(status="ok", app_env=config.app_env)
