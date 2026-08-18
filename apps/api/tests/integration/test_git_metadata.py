import subprocess
from pathlib import Path

import pytest

from app.infrastructure.repository.git_metadata import (
    GitMetadataReader,
    NonGitRepositoryError,
    SubprocessGitCommandRunner,
    UnsafeGitCommandError,
)


def test_git_metadata_reads_committed_repo(tmp_path: Path) -> None:
    repository = init_git_repository(tmp_path / "repo")
    (repository / "README.md").write_text("hello\n", encoding="utf-8")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "initial")

    metadata = GitMetadataReader(allowed_roots=(tmp_path,)).read(repository)

    assert metadata.commit_sha == git(repository, "rev-parse", "HEAD")
    assert metadata.branch in {"main", "master"}
    assert metadata.dirty is False
    assert metadata.tree_hash
    assert metadata.non_git is False


def test_git_metadata_dirty_repo_keeps_required_tree_hash(tmp_path: Path) -> None:
    repository = init_git_repository(tmp_path / "repo")
    (repository / "README.md").write_text("hello\n", encoding="utf-8")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "initial")
    clean_metadata = GitMetadataReader(allowed_roots=(tmp_path,)).read(repository)

    (repository / "README.md").write_text("hello changed\n", encoding="utf-8")
    (repository / "new.py").write_text("print('new')\n", encoding="utf-8")
    dirty_metadata = GitMetadataReader(allowed_roots=(tmp_path,)).read(repository)

    assert dirty_metadata.commit_sha == clean_metadata.commit_sha
    assert dirty_metadata.dirty is True
    assert dirty_metadata.tree_hash
    assert dirty_metadata.tree_hash != clean_metadata.tree_hash


def test_non_git_repository_requires_explicit_flag(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "README.md").write_text("hello\n", encoding="utf-8")

    with pytest.raises(NonGitRepositoryError):
        GitMetadataReader(allowed_roots=(tmp_path,)).read(repository)

    metadata = GitMetadataReader(allowed_roots=(tmp_path,), allow_non_git=True).read(repository)

    assert metadata.commit_sha is None
    assert metadata.branch is None
    assert metadata.dirty is True
    assert metadata.tree_hash
    assert metadata.non_git is True


def test_git_runner_rejects_non_allowlisted_commands(tmp_path: Path) -> None:
    with pytest.raises(UnsafeGitCommandError):
        SubprocessGitCommandRunner().run(
            ("clean", "-fdx"),
            cwd=tmp_path,
            timeout_seconds=10,
        )


def init_git_repository(repository: Path) -> Path:
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.email", "test@example.invalid")
    git(repository, "config", "user.name", "Test User")
    return repository


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )
    return result.stdout.strip()
