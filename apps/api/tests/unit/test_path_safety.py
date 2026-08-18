from pathlib import Path

import pytest

from app.core.security import (
    RepositoryPathNotAllowedError,
    RepositoryPathTraversalError,
    SymlinkEscapeError,
    validate_repository_root,
)
from app.infrastructure.repository.file_reader import SafeFileReader
from app.infrastructure.repository.scanner import RepositoryPathScanner


def test_repository_root_is_canonicalized_and_must_be_allowlisted(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    repository = allowed_root / "repo"
    repository.mkdir(parents=True)

    canonical = validate_repository_root(
        repository / ".." / "repo",
        allowed_roots=(allowed_root,),
    )

    assert canonical == repository.resolve()

    with pytest.raises(RepositoryPathNotAllowedError, match="outside"):
        validate_repository_root(repository, allowed_roots=(tmp_path / "other",))


def test_filesystem_root_and_home_without_allowlist_are_rejected(tmp_path: Path) -> None:
    filesystem_root = Path(tmp_path.anchor)

    with pytest.raises(RepositoryPathNotAllowedError, match="Filesystem root"):
        validate_repository_root(filesystem_root, allowed_roots=(filesystem_root,))

    with pytest.raises(RepositoryPathNotAllowedError, match="outside"):
        validate_repository_root(Path.home(), allowed_roots=(tmp_path,))


def test_safe_file_reader_rejects_path_traversal_and_reads_posix_style_paths(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    source_dir = repository / "src"
    source_dir.mkdir(parents=True)
    (source_dir / "main.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "outside.py").write_text("print('escape')", encoding="utf-8")
    reader = SafeFileReader(repository)

    assert reader.read_text("src/main.py") == "print('ok')"

    with pytest.raises(RepositoryPathTraversalError):
        reader.read_text("../outside.py")


def test_safe_file_reader_rejects_symlink_escape(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret", encoding="utf-8")
    symlink = repository / "link.txt"
    create_symlink_or_skip(symlink, outside_file)

    with pytest.raises(SymlinkEscapeError):
        SafeFileReader(repository).read_text("link.txt")


def test_scanner_reports_broken_symlink_warning_without_crashing(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    repository = allowed_root / "repo"
    repository.mkdir(parents=True)
    (repository / "README.md").write_text("ok", encoding="utf-8")
    broken_symlink = repository / "broken-link"
    create_symlink_or_skip(broken_symlink, repository / "missing.txt")

    scan = RepositoryPathScanner(allowed_roots=(allowed_root,)).scan_paths(repository)

    assert [entry.relative_path for entry in scan.entries] == ["README.md"]
    assert len(scan.warnings) == 1
    assert scan.warnings[0].code == "BROKEN_SYMLINK"
    assert scan.warnings[0].path == broken_symlink


def create_symlink_or_skip(link_path: Path, target_path: Path) -> None:
    try:
        link_path.symlink_to(target_path)
    except OSError as exc:
        pytest.skip(f"symlink creation is not available in this environment: {exc}")
