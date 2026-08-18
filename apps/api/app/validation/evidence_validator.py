from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from app.contracts.graph import Evidence, ValidationIssue, ValidationResult
from app.core.security import PathSafetyError, resolve_repository_child_path
from app.domain.enums import ReasonCode, ValidationState
from app.infrastructure.repository.scanner import FileIndexStatus, RepositoryFileIndex


@dataclass(frozen=True)
class EvidenceValidationOutcome:
    result: ValidationResult
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.result.state == ValidationState.CONFIRMED


class EvidenceIntegrityValidator:
    validator_name = "evidence_integrity"

    def __init__(self, repository_root: str | Path, file_index: RepositoryFileIndex) -> None:
        self.repository_root = Path(repository_root)
        self.files_by_path = {record.relative_path: record for record in file_index.files}

    def validate(self, evidence: Evidence) -> EvidenceValidationOutcome:
        try:
            safe_path = resolve_repository_child_path(self.repository_root, evidence.relative_path)
        except PathSafetyError as exc:
            return self._reject(
                message="evidence path escapes repository root",
                reason_codes=(ReasonCode.EVIDENCE_INVALID,),
                metadata={"relative_path": evidence.relative_path, "error": str(exc)},
            )
        file_record = self.files_by_path.get(evidence.relative_path)
        if file_record is None:
            return self._reject(
                message="evidence file is not present in repository snapshot",
                reason_codes=(ReasonCode.EVIDENCE_INVALID,),
                metadata={"relative_path": evidence.relative_path},
            )
        if file_record.status != FileIndexStatus.INDEXED:
            return self._reject(
                message="evidence references an excluded or unreadable file",
                reason_codes=(ReasonCode.EVIDENCE_INVALID,),
                metadata={
                    "relative_path": evidence.relative_path,
                    "file_status": file_record.status.value,
                    "reason": file_record.reason,
                },
            )
        if file_record.sha256 != evidence.file_hash:
            return self._reject(
                message="evidence file hash is stale",
                reason_codes=(
                    ReasonCode.STALE_SOURCE,
                    ReasonCode.REPOSITORY_CHANGED_DURING_AUDIT,
                ),
                state=ValidationState.STALE,
                metadata={
                    "relative_path": evidence.relative_path,
                    "expected_file_hash": evidence.file_hash,
                    "actual_file_hash": file_record.sha256,
                },
            )
        try:
            content = safe_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            return self._reject(
                message="evidence file is not readable as UTF-8",
                reason_codes=(ReasonCode.EVIDENCE_INVALID,),
                metadata={"relative_path": evidence.relative_path, "error": str(exc)},
            )
        lines = content.splitlines()
        if evidence.line_end > len(lines):
            return self._reject(
                message="evidence line range is outside file",
                reason_codes=(ReasonCode.EVIDENCE_INVALID,),
                metadata={
                    "relative_path": evidence.relative_path,
                    "line_start": evidence.line_start,
                    "line_end": evidence.line_end,
                    "line_count": len(lines),
                },
            )
        fragment = "\n".join(lines[evidence.line_start - 1 : evidence.line_end])
        if evidence.fragment_hash is not None and _fragment_hash(fragment) != evidence.fragment_hash:
            return self._reject(
                message="evidence fragment hash does not match source",
                reason_codes=(ReasonCode.EVIDENCE_INVALID,),
                metadata={
                    "relative_path": evidence.relative_path,
                    "line_start": evidence.line_start,
                    "line_end": evidence.line_end,
                },
            )
        if (
            evidence.source_fragment_marker is not None
            and evidence.source_fragment_marker not in fragment
        ):
            return self._reject(
                message="evidence source fragment marker is missing",
                reason_codes=(ReasonCode.EVIDENCE_INVALID,),
                metadata={
                    "relative_path": evidence.relative_path,
                    "line_start": evidence.line_start,
                    "line_end": evidence.line_end,
                },
            )
        return EvidenceValidationOutcome(
            result=ValidationResult(
                validator_name=self.validator_name,
                state=ValidationState.CONFIRMED,
                reason_codes=(),
                message="evidence matches repository snapshot",
                metadata={"relative_path": evidence.relative_path},
            )
        )

    def _reject(
        self,
        *,
        message: str,
        reason_codes: tuple[ReasonCode, ...],
        metadata: dict[str, object],
        state: ValidationState = ValidationState.REJECTED,
    ) -> EvidenceValidationOutcome:
        result = ValidationResult(
            validator_name=self.validator_name,
            state=state,
            reason_codes=reason_codes,
            message=message,
            metadata=metadata,
        )
        return EvidenceValidationOutcome(
            result=result,
            issues=tuple(
                ValidationIssue(
                    issue_id=str(uuid4()),
                    reason_code=reason_code,
                    state=state,
                    message=message,
                    metadata=metadata,
                )
                for reason_code in reason_codes
            ),
        )


def _fragment_hash(fragment: str) -> str:
    return f"sha256:{sha256(fragment.encode('utf-8')).hexdigest()}"
