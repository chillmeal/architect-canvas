from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


class DatabaseConfigurationError(ValueError):
    pass


def create_sqlite_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.drivername != "sqlite":
        raise DatabaseConfigurationError("Only sqlite database URLs are supported in MVP")

    connect_args = {"check_same_thread": False}
    engine = create_engine(database_url, connect_args=connect_args, future=True)
    _configure_sqlite_pragmas(engine)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _configure_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def get_sqlite_pragma(engine: Engine, pragma_name: str) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text(f"PRAGMA {pragma_name}")).scalar_one())
