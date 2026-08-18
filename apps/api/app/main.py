from fastapi import FastAPI

from app.api.error_handlers import register_error_handlers
from app.api.routers.audits import router as audits_router
from app.api.routers.graphs import router as graphs_router
from app.api.routers.health import router as health_router
from app.api.routers.projects import router as projects_router
from app.core.config import AppConfig
from app.core.logging import configure_logging
from app.infrastructure.db.session import create_session_factory, create_sqlite_engine
from app.infrastructure.llm import LlmProvider
from app.infrastructure.queue.in_memory import InMemoryAuditQueue


def create_app(
    config: AppConfig | None = None,
    *,
    llm_provider: LlmProvider | None = None,
) -> FastAPI:
    app_config = config or AppConfig.from_environment()
    app = FastAPI(title="Architecture Visualizer API", version="0.1.0")
    app.state.config = app_config
    app.state.engine = create_sqlite_engine(app_config.database_url)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.audit_queue = InMemoryAuditQueue(max_concurrency=1, job_timeout_seconds=3600)
    if llm_provider is not None:
        app.state.llm_provider = llm_provider
    app.state.logger = configure_logging(app_config)
    register_error_handlers(app)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(audits_router, prefix="/api/v1")
    app.include_router(graphs_router, prefix="/api/v1")
    return app


app = create_app()
