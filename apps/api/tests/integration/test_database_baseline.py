from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.infrastructure.db.session import (
    DatabaseConfigurationError,
    create_session_factory,
    create_sqlite_engine,
    get_sqlite_pragma,
    session_scope,
)


def test_sqlite_engine_enables_foreign_keys_and_wal(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_sqlite_engine(database_url)

    assert get_sqlite_pragma(engine, "foreign_keys") == "1"
    assert get_sqlite_pragma(engine, "journal_mode").lower() == "wal"


def test_sqlite_engine_rejects_non_sqlite_urls() -> None:
    with pytest.raises(DatabaseConfigurationError, match="Only sqlite"):
        create_sqlite_engine("postgresql://localhost/app")


def test_session_scope_commits_and_rolls_back(tmp_path: Path) -> None:
    engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'app.db'}")
    session_factory = create_session_factory(engine)

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))

    with session_scope(session_factory) as session:
        session.execute(text("INSERT INTO sample (name) VALUES ('committed')"))

    with pytest.raises(RuntimeError, match="force rollback"), session_scope(
        session_factory
    ) as session:
        session.execute(text("INSERT INTO sample (name) VALUES ('rolled-back')"))
        raise RuntimeError("force rollback")

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT name FROM sample ORDER BY id")).scalars().all()

    assert rows == ["committed"]


def test_alembic_upgrade_head_creates_version_table(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    engine = create_sqlite_engine(database_url)
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert version == "0003_graph_snapshots_revisions"
