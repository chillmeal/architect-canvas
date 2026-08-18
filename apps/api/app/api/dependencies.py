from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppConfig
from app.infrastructure.db.session import session_scope
from app.infrastructure.llm import GigaChatProvider, LlmProvider
from app.infrastructure.queue.in_memory import InMemoryAuditQueue


def get_app_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_scope(session_factory) as session:
        yield session


def get_session_factory(request: Request) -> sessionmaker[Session]:
    return request.app.state.session_factory


def get_llm_provider(request: Request) -> LlmProvider:
    llm_provider = getattr(request.app.state, "llm_provider", None)
    if llm_provider is not None:
        return llm_provider
    llm_provider = GigaChatProvider.from_config(request.app.state.config)
    request.app.state.llm_provider = llm_provider
    return llm_provider


def get_audit_queue(request: Request) -> InMemoryAuditQueue:
    return request.app.state.audit_queue
