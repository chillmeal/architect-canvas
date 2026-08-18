# Domain Model

The domain model is defined by `docs/ARCHITECTURE.md`, sections 7, 8, 11, 13, and 14.

## Implemented Bootstrap Contracts

- `NodeType` and `EdgeType` mirror the graph ontology from architecture section 7.
- `ValidationState`, `AuditStatus`, `OverrideOperation`, `EntityOrigin`, `LlmValidatorDecision`, evidence enums, and reason codes are explicit domain enums.
- Unknown enum values must be rejected through the domain parser instead of silently mapped.
- `StableLogicalKey` is a value object built from project, node type, owner path, display name, and at least one identity signal such as artifact, package, deployment, or repository path.

## Pydantic Contracts

- `Evidence` requires source location, file hash, line range, source type, strength, analysis unit id, and either `fragmentHash` or `sourceFragmentMarker`.
- `CandidateFact`, `GraphNode`, `GraphEdge`, `GraphSnapshot`, `ValidationResult`, `ValidationIssue`, and `ValidationRecord` are Pydantic contracts with extra fields forbidden.
- Inferred graph nodes and edges are invalid without evidence.
- JSON Schema files in `contracts/` are generated from Pydantic models by `scripts/generate_contract_schemas.py`.

## Confidence Policy

- Final confidence is calculated by backend policy, not by the model.
- Thresholds are configurable through `CONFIDENCE_CONFIRMED_MIN`, `CONFIDENCE_WARNINGS_MIN`, and `CONFIDENCE_REVIEW_MIN`.
- Hard domain invariants and evidence integrity failures have priority over analyzer and LLM-validator opinions.
- The policy implements the conflict-resolution rules from architecture section 11.9.

## Persistence Baseline

- SQLite is initialized through SQLAlchemy and Alembic only.
- SQLite sessions enable `foreign_keys=ON` and `journal_mode=WAL`.
- The first migration is `0001_baseline`; audit storage starts in `0002_audits_events_storage`.
- Runtime database files remain under `var/data` and are ignored by VCS.
- Project, RepositoryState, Audit, AuditStage, and AuditEvent are persisted through repository classes.
- Audit terminal statuses are immutable through repository update APIs.
- AuditEvent ordering is deterministic by per-audit `sequence_number` and supports pagination.
