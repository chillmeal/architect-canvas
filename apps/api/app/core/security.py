from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class PathSafetyError(ValueError):
    pass


class RepositoryPathNotAllowedError(PathSafetyError):
    pass


class RepositoryPathTraversalError(PathSafetyError):
    pass


class SymlinkEscapeError(PathSafetyError):
    pass


@dataclass(frozen=True)
class PathSafetyWarning:
    code: str
    path: Path
    message: str


def canonicalize_path(path: str | Path) -> Path:
    return Path(os.path.realpath(os.fspath(path)))


def validate_repository_root(
    repository_path: str | Path,
    allowed_roots: tuple[Path, ...],
) -> Path:
    canonical_repository_path = canonicalize_path(repository_path)
    if not canonical_repository_path.exists():
        raise RepositoryPathNotAllowedError(
            f"Repository path does not exist: {canonical_repository_path}"
        )
    if not canonical_repository_path.is_dir():
        raise RepositoryPathNotAllowedError(
            f"Repository path is not a directory: {canonical_repository_path}"
        )
    if _is_filesystem_root(canonical_repository_path):
        raise RepositoryPathNotAllowedError("Filesystem root cannot be used as repository path")
    canonical_allowed_roots = tuple(canonicalize_path(root) for root in allowed_roots)
    if not canonical_allowed_roots:
        raise RepositoryPathNotAllowedError("REPOSITORY_ALLOWED_ROOTS is empty")
    if not any(_is_relative_to(canonical_repository_path, root) for root in canonical_allowed_roots):
        raise RepositoryPathNotAllowedError(
            f"Repository path is outside REPOSITORY_ALLOWED_ROOTS: {canonical_repository_path}"
        )
    return canonical_repository_path


def resolve_repository_child_path(
    repository_root: str | Path,
    requested_path: str | Path,
) -> Path:
    root = canonicalize_path(repository_root)
    requested = Path(requested_path)
    if _has_traversal_segment(requested):
        raise RepositoryPathTraversalError(f"Path traversal is forbidden: {requested_path}")
    candidate = requested if requested.is_absolute() else root / requested
    canonical_candidate = canonicalize_path(candidate)
    if not _is_relative_to(canonical_candidate, root):
        raise SymlinkEscapeError(f"Path escapes repository root: {requested_path}")
    return canonical_candidate


def is_broken_symlink(path: str | Path) -> bool:
    candidate = Path(path)
    return candidate.is_symlink() and not candidate.exists()


def _has_traversal_segment(path: Path) -> bool:
    return any(part == ".." for part in path.parts)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_filesystem_root(path: Path) -> bool:
    return path == path.anchor or path.parent == path
