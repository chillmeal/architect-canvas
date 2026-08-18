from hashlib import sha256
from pathlib import Path

from app.infrastructure.repository.scanner import FileIndexStatus, RepositoryFileIndexer


def test_file_indexer_applies_gitignore_precedence(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".gitignore").write_text("*.log\n!important.log\n", encoding="utf-8")
    (repository / "debug.log").write_text("ignored", encoding="utf-8")
    (repository / "important.log").write_text("kept", encoding="utf-8")

    index = RepositoryFileIndexer(
        allowed_roots=(tmp_path,),
        max_file_bytes=1024,
    ).index_files(repository)
    records = {record.relative_path: record for record in index.files}

    assert records["debug.log"].status == FileIndexStatus.IGNORED
    assert records["important.log"].status == FileIndexStatus.INDEXED
    assert records["important.log"].readable is True


def test_file_indexer_applies_system_exclusions(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    (repository / ".git").mkdir(parents=True)
    (repository / "node_modules" / "pkg").mkdir(parents=True)
    (repository / "src").mkdir()
    (repository / ".git" / "config").write_text("ignored", encoding="utf-8")
    (repository / "node_modules" / "pkg" / "index.js").write_text("ignored", encoding="utf-8")
    (repository / "src" / "client.generated.ts").write_text("ignored", encoding="utf-8")
    (repository / "src" / "bundle.min.js").write_text("ignored", encoding="utf-8")
    (repository / "src" / "logo.png").write_bytes(b"png")
    (repository / "src" / "archive.zip").write_bytes(b"zip")

    index = RepositoryFileIndexer(
        allowed_roots=(tmp_path,),
        max_file_bytes=1024,
    ).index_files(repository)
    records = {record.relative_path: record for record in index.files}

    assert records[".git/config"].status == FileIndexStatus.EXCLUDED
    assert records["node_modules/pkg/index.js"].status == FileIndexStatus.EXCLUDED
    assert records["src/client.generated.ts"].reason == "GENERATED_CLIENT"
    assert records["src/bundle.min.js"].reason == "MINIFIED"
    assert records["src/logo.png"].reason == "IMAGE"
    assert records["src/archive.zip"].reason == "ARCHIVE"


def test_file_indexer_detects_binary_files(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    content = b"abc\x00def"
    (repository / "data.bin").write_bytes(content)

    index = RepositoryFileIndexer(
        allowed_roots=(tmp_path,),
        max_file_bytes=1024,
    ).index_files(repository)
    record = index.files[0]

    assert record.relative_path == "data.bin"
    assert record.status == FileIndexStatus.BINARY
    assert record.readable is False
    assert record.sha256 == sha256(content).hexdigest()


def test_file_indexer_marks_oversized_files_without_readability(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    content = b"123456"
    (repository / "large.py").write_bytes(content)

    index = RepositoryFileIndexer(
        allowed_roots=(tmp_path,),
        max_file_bytes=5,
    ).index_files(repository)
    record = index.files[0]

    assert record.status == FileIndexStatus.OVERSIZED
    assert record.language == "python"
    assert record.size_bytes == len(content)
    assert record.sha256 == sha256(content).hexdigest()
    assert record.readable is False


def test_file_indexer_marks_encoding_failures_as_unreadable(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    content = b"invalid utf-8: \xff"
    (repository / "source.py").write_bytes(content)

    index = RepositoryFileIndexer(
        allowed_roots=(tmp_path,),
        max_file_bytes=1024,
    ).index_files(repository)
    record = index.files[0]

    assert record.status == FileIndexStatus.UNREADABLE
    assert record.language == "python"
    assert record.sha256 == sha256(content).hexdigest()
    assert record.readable is False
