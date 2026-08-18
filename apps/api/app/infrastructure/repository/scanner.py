from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from app.core.security import (
    PathSafetyWarning,
    is_broken_symlink,
    resolve_repository_child_path,
    validate_repository_root,
)
from app.infrastructure.repository.ignore_rules import (
    RepositoryIgnoreRules,
    system_exclusion_reason,
)


class FileIndexStatus(StrEnum):
    INDEXED = "INDEXED"
    IGNORED = "IGNORED"
    EXCLUDED = "EXCLUDED"
    BINARY = "BINARY"
    OVERSIZED = "OVERSIZED"
    UNREADABLE = "UNREADABLE"


LANGUAGE_BY_EXTENSION = {
    ".cs": "csharp",
    ".css": "css",
    ".go": "go",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".json": "json",
    ".kt": "kotlin",
    ".md": "markdown",
    ".php": "php",
    ".py": "python",
    ".rs": "rust",
    ".sql": "sql",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}


@dataclass(frozen=True)
class RepositoryPathEntry:
    path: Path
    relative_path: str


@dataclass(frozen=True)
class RepositoryPathScan:
    entries: tuple[RepositoryPathEntry, ...]
    warnings: tuple[PathSafetyWarning, ...]


@dataclass(frozen=True)
class FileIndexRecord:
    relative_path: str
    size_bytes: int
    language: str | None
    status: FileIndexStatus
    sha256: str
    readable: bool
    reason: str | None = None


@dataclass(frozen=True)
class RepositoryFileIndex:
    files: tuple[FileIndexRecord, ...]
    warnings: tuple[PathSafetyWarning, ...]


class RepositoryPathScanner:
    def __init__(self, allowed_roots: tuple[Path, ...]) -> None:
        self.allowed_roots = allowed_roots

    def scan_paths(self, repository_root: str | Path) -> RepositoryPathScan:
        root = validate_repository_root(repository_root, self.allowed_roots)
        entries: list[RepositoryPathEntry] = []
        warnings: list[PathSafetyWarning] = []
        for candidate in root.rglob("*"):
            if is_broken_symlink(candidate):
                warnings.append(
                    PathSafetyWarning(
                        code="BROKEN_SYMLINK",
                        path=candidate,
                        message="Broken symlink skipped",
                    )
                )
                continue
            try:
                safe_path = resolve_repository_child_path(root, candidate)
            except ValueError as exc:
                warnings.append(
                    PathSafetyWarning(
                        code="PATH_SKIPPED",
                        path=candidate,
                        message=str(exc),
                    )
                )
                continue
            entries.append(
                RepositoryPathEntry(
                    path=safe_path,
                    relative_path=safe_path.relative_to(root).as_posix(),
                )
            )
        return RepositoryPathScan(entries=tuple(entries), warnings=tuple(warnings))


class RepositoryFileIndexer:
    def __init__(self, allowed_roots: tuple[Path, ...], *, max_file_bytes: int) -> None:
        self.allowed_roots = allowed_roots
        self.max_file_bytes = max_file_bytes

    def index_files(self, repository_root: str | Path) -> RepositoryFileIndex:
        root = validate_repository_root(repository_root, self.allowed_roots)
        ignore_rules = _load_root_ignore_rules(root)
        records: list[FileIndexRecord] = []
        warnings: list[PathSafetyWarning] = []
        for candidate in _iter_repository_paths(root):
            if is_broken_symlink(candidate):
                warnings.append(
                    PathSafetyWarning(
                        code="BROKEN_SYMLINK",
                        path=candidate,
                        message="Broken symlink skipped",
                    )
                )
                continue
            try:
                safe_path = resolve_repository_child_path(root, candidate)
            except ValueError as exc:
                warnings.append(
                    PathSafetyWarning(code="PATH_SKIPPED", path=candidate, message=str(exc))
                )
                continue
            if not safe_path.is_file():
                continue
            relative_path = safe_path.relative_to(root).as_posix()
            records.append(self._index_file(safe_path, relative_path, ignore_rules))
        records.sort(key=lambda record: record.relative_path)
        return RepositoryFileIndex(files=tuple(records), warnings=tuple(warnings))

    def _index_file(
        self,
        path: Path,
        relative_path: str,
        ignore_rules: RepositoryIgnoreRules,
    ) -> FileIndexRecord:
        size_bytes = path.stat().st_size
        digest = _hash_file(path)
        language = _detect_language(path)
        system_reason = system_exclusion_reason(relative_path)
        if system_reason is not None:
            return FileIndexRecord(
                relative_path=relative_path,
                size_bytes=size_bytes,
                language=language,
                status=FileIndexStatus.EXCLUDED,
                sha256=digest,
                readable=False,
                reason=system_reason,
            )
        if ignore_rules.is_ignored(relative_path):
            return FileIndexRecord(
                relative_path=relative_path,
                size_bytes=size_bytes,
                language=language,
                status=FileIndexStatus.IGNORED,
                sha256=digest,
                readable=False,
                reason="GITIGNORE",
            )
        if size_bytes > self.max_file_bytes:
            return FileIndexRecord(
                relative_path=relative_path,
                size_bytes=size_bytes,
                language=language,
                status=FileIndexStatus.OVERSIZED,
                sha256=digest,
                readable=False,
                reason="MAX_FILE_BYTES",
            )
        sample = path.read_bytes()
        if _is_binary(sample):
            return FileIndexRecord(
                relative_path=relative_path,
                size_bytes=size_bytes,
                language=language,
                status=FileIndexStatus.BINARY,
                sha256=digest,
                readable=False,
                reason="BINARY_CONTENT",
            )
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            return FileIndexRecord(
                relative_path=relative_path,
                size_bytes=size_bytes,
                language=language,
                status=FileIndexStatus.UNREADABLE,
                sha256=digest,
                readable=False,
                reason="ENCODING",
            )
        return FileIndexRecord(
            relative_path=relative_path,
            size_bytes=size_bytes,
            language=language,
            status=FileIndexStatus.INDEXED,
            sha256=digest,
            readable=True,
        )


def _iter_repository_paths(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix()))


def _load_root_ignore_rules(root: Path) -> RepositoryIgnoreRules:
    ignore_file = root / ".gitignore"
    if not ignore_file.is_file():
        return RepositoryIgnoreRules()
    try:
        content = ignore_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return RepositoryIgnoreRules()
    return RepositoryIgnoreRules.parse(content)


def _hash_file(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _detect_language(path: Path) -> str | None:
    return LANGUAGE_BY_EXTENSION.get(path.suffix.lower())


def _is_binary(content: bytes) -> bool:
    if b"\x00" in content:
        return True
    if not content:
        return False
    non_text = sum(byte < 9 or 13 < byte < 32 for byte in content)
    return non_text / len(content) > 0.30
