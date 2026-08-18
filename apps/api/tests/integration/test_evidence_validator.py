from hashlib import sha256
from pathlib import Path

from app.contracts.graph import Evidence
from app.domain.enums import EvidenceSourceType, EvidenceStrength, ReasonCode, ValidationState
from app.infrastructure.repository.scanner import RepositoryFileIndexer
from app.validation import EvidenceIntegrityValidator


def test_evidence_validator_accepts_matching_snapshot_evidence(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    source = repository / "src" / "main.py"
    source.write_text("def app():\n    return 'ok'\n", encoding="utf-8")
    file_index = index_repository(tmp_path, repository)
    evidence = make_evidence(
        relative_path="src/main.py",
        file_hash=record_hash(file_index, "src/main.py"),
        line_start=1,
        line_end=1,
        fragment_hash=fragment_hash("def app():"),
    )

    outcome = EvidenceIntegrityValidator(repository, file_index).validate(evidence)

    assert outcome.accepted is True
    assert outcome.result.state == ValidationState.CONFIRMED
    assert outcome.issues == ()


def test_evidence_validator_marks_stale_source_on_file_hash_change(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    source = repository / "src" / "main.py"
    source.write_text("def app():\n    return 'ok'\n", encoding="utf-8")
    stale_hash = "sha256:old"
    file_index = index_repository(tmp_path, repository)

    outcome = EvidenceIntegrityValidator(repository, file_index).validate(
        make_evidence(
            relative_path="src/main.py",
            file_hash=stale_hash,
            line_start=1,
            line_end=1,
            fragment_hash=fragment_hash("def app():"),
        )
    )

    assert outcome.result.state == ValidationState.STALE
    assert outcome.result.reason_codes == (
        ReasonCode.STALE_SOURCE,
        ReasonCode.REPOSITORY_CHANGED_DURING_AUDIT,
    )
    assert [issue.reason_code for issue in outcome.issues] == [
        ReasonCode.STALE_SOURCE,
        ReasonCode.REPOSITORY_CHANGED_DURING_AUDIT,
    ]


def test_evidence_validator_rejects_wrong_line_range(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    source = repository / "src" / "main.py"
    source.write_text("one\n", encoding="utf-8")
    file_index = index_repository(tmp_path, repository)

    outcome = EvidenceIntegrityValidator(repository, file_index).validate(
        make_evidence(
            relative_path="src/main.py",
            file_hash=record_hash(file_index, "src/main.py"),
            line_start=1,
            line_end=2,
            fragment_hash=fragment_hash("one"),
        )
    )

    assert outcome.accepted is False
    assert outcome.result.reason_codes == (ReasonCode.EVIDENCE_INVALID,)


def test_evidence_validator_rejects_fragment_hash_mismatch(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    source = repository / "src" / "main.py"
    source.write_text("actual\n", encoding="utf-8")
    file_index = index_repository(tmp_path, repository)

    outcome = EvidenceIntegrityValidator(repository, file_index).validate(
        make_evidence(
            relative_path="src/main.py",
            file_hash=record_hash(file_index, "src/main.py"),
            line_start=1,
            line_end=1,
            fragment_hash=fragment_hash("different"),
        )
    )

    assert outcome.accepted is False
    assert outcome.result.reason_codes == (ReasonCode.EVIDENCE_INVALID,)


def test_evidence_validator_rejects_path_escape(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    (repository / "src" / "main.py").write_text("ok\n", encoding="utf-8")
    (tmp_path / "outside.py").write_text("escape\n", encoding="utf-8")
    file_index = index_repository(tmp_path, repository)

    escaped = make_evidence(
        relative_path="../outside.py",
        file_hash="sha256:any",
        line_start=1,
        line_end=1,
        fragment_hash=fragment_hash("escape"),
    )
    outcome = EvidenceIntegrityValidator(repository, file_index).validate(escaped)

    assert outcome.accepted is False
    assert outcome.result.reason_codes == (ReasonCode.EVIDENCE_INVALID,)


def test_evidence_validator_rejects_excluded_file_status(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    (repository / "node_modules" / "pkg").mkdir(parents=True)
    excluded = repository / "node_modules" / "pkg" / "index.js"
    excluded.write_text("module.exports = {}\n", encoding="utf-8")
    file_index = index_repository(tmp_path, repository)

    outcome = EvidenceIntegrityValidator(repository, file_index).validate(
        make_evidence(
            relative_path="node_modules/pkg/index.js",
            file_hash=record_hash(file_index, "node_modules/pkg/index.js"),
            line_start=1,
            line_end=1,
            fragment_hash=fragment_hash("module.exports = {}"),
        )
    )

    assert outcome.accepted is False
    assert outcome.result.reason_codes == (ReasonCode.EVIDENCE_INVALID,)
    assert outcome.result.metadata["file_status"] == "EXCLUDED"


def make_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    (repository / "src").mkdir(parents=True)
    return repository


def index_repository(tmp_path: Path, repository: Path):
    return RepositoryFileIndexer(allowed_roots=(tmp_path,), max_file_bytes=100_000).index_files(
        repository
    )


def record_hash(file_index, relative_path: str) -> str:
    return next(record.sha256 for record in file_index.files if record.relative_path == relative_path)


def make_evidence(
    *,
    relative_path: str,
    file_hash: str,
    line_start: int,
    line_end: int,
    fragment_hash: str,
) -> Evidence:
    return Evidence(
        evidence_id="evidence-1",
        relative_path=relative_path,
        file_hash=file_hash,
        line_start=line_start,
        line_end=line_end,
        fragment_hash=fragment_hash,
        source_type=EvidenceSourceType.SOURCE_CODE,
        strength=EvidenceStrength.STRONG,
        analysis_unit_id="unit-1",
    )


def fragment_hash(fragment: str) -> str:
    return f"sha256:{sha256(fragment.encode('utf-8')).hexdigest()}"
