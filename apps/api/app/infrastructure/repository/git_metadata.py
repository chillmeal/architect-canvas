from __future__ import annotations

import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from app.core.security import resolve_repository_child_path, validate_repository_root

ALLOWED_GIT_COMMANDS = frozenset(
    {
        ("rev-parse", "--is-inside-work-tree"),
        ("rev-parse", "HEAD"),
        ("branch", "--show-current"),
        ("status", "--porcelain=v1", "--untracked-files=all"),
        ("ls-files", "-z", "--cached", "--others", "--exclude-standard"),
    }
)


class GitMetadataError(RuntimeError):
    pass


class NonGitRepositoryError(GitMetadataError):
    pass


class UnsafeGitCommandError(GitMetadataError):
    pass


class CommandRunner(Protocol):
    def run(self, args: tuple[str, ...], *, cwd: Path, timeout_seconds: int) -> str:
        pass


@dataclass(frozen=True)
class RepositoryGitMetadata:
    commit_sha: str | None
    branch: str | None
    dirty: bool
    tree_hash: str
    non_git: bool = False


class SubprocessGitCommandRunner:
    def run(self, args: tuple[str, ...], *, cwd: Path, timeout_seconds: int) -> str:
        if args not in ALLOWED_GIT_COMMANDS:
            raise UnsafeGitCommandError(f"Git command is not allowlisted: {' '.join(args)}")
        result = subprocess.run(
            ("git", *args),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
        if result.returncode != 0:
            raise GitMetadataError(result.stderr.strip() or result.stdout.strip() or "git failed")
        return result.stdout


class GitMetadataReader:
    def __init__(
        self,
        allowed_roots: tuple[Path, ...],
        *,
        allow_non_git: bool = False,
        timeout_seconds: int = 10,
        runner: CommandRunner | None = None,
    ) -> None:
        self.allowed_roots = allowed_roots
        self.allow_non_git = allow_non_git
        self.timeout_seconds = timeout_seconds
        self.runner = runner or SubprocessGitCommandRunner()

    def read(self, repository_root: str | Path) -> RepositoryGitMetadata:
        root = validate_repository_root(repository_root, self.allowed_roots)
        try:
            inside_work_tree = self._git(root, ("rev-parse", "--is-inside-work-tree")).strip()
        except GitMetadataError as exc:
            if self.allow_non_git:
                return RepositoryGitMetadata(
                    commit_sha=None,
                    branch=None,
                    dirty=True,
                    tree_hash=_hash_all_repository_files(root),
                    non_git=True,
                )
            raise NonGitRepositoryError("Repository is not a Git work tree") from exc
        if inside_work_tree != "true":
            if self.allow_non_git:
                return RepositoryGitMetadata(
                    commit_sha=None,
                    branch=None,
                    dirty=True,
                    tree_hash=_hash_all_repository_files(root),
                    non_git=True,
                )
            raise NonGitRepositoryError("Repository is not a Git work tree")

        commit_sha = self._git(root, ("rev-parse", "HEAD")).strip()
        branch = self._git(root, ("branch", "--show-current")).strip() or None
        status = self._git(root, ("status", "--porcelain=v1", "--untracked-files=all"))
        tracked_and_untracked = self._git(
            root,
            ("ls-files", "-z", "--cached", "--others", "--exclude-standard"),
        )
        return RepositoryGitMetadata(
            commit_sha=commit_sha,
            branch=branch,
            dirty=bool(status.strip()),
            tree_hash=_hash_git_file_list(root, tracked_and_untracked),
            non_git=False,
        )

    def _git(self, cwd: Path, args: tuple[str, ...]) -> str:
        return self.runner.run(args, cwd=cwd, timeout_seconds=self.timeout_seconds)


def _hash_git_file_list(root: Path, raw_paths: str) -> str:
    relative_paths = tuple(
        sorted(item for item in raw_paths.split("\0") if item and not item.endswith("/"))
    )
    hasher = sha256()
    for relative_path in relative_paths:
        path = resolve_repository_child_path(root, relative_path)
        if not path.is_file():
            continue
        _update_tree_hash(hasher, relative_path, path)
    return hasher.hexdigest()


def _hash_all_repository_files(root: Path) -> str:
    hasher = sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        _update_tree_hash(hasher, relative_path, path)
    return hasher.hexdigest()


def _update_tree_hash(hasher, relative_path: str, path: Path) -> None:
    hasher.update(relative_path.encode("utf-8"))
    hasher.update(b"\0")
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            hasher.update(chunk)
    hasher.update(b"\0")
