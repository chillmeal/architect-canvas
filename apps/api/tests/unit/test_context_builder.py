import json
from hashlib import sha256
from pathlib import Path

from app.analysis.context_builder import UNTRUSTED_SOURCE_GUARD, AnalysisUnitContextBuilder
from app.infrastructure.llm import TokenBudget
from app.infrastructure.repository.unit_detector import AnalysisUnit


def test_context_builder_orders_redacts_and_marks_untrusted_source(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    write(repository / "package.json", '{"name":"payments","dependencies":{"fastify":"1.0.0"}}')
    write(repository / ".env", "TOKEN=secret-value\n")
    write(repository / "src" / "index.ts", "Authorization: Bearer abc.def.ghi\nconsole.log('ok')\n")
    manifest = write_prompt_manifest(tmp_path)
    unit = make_unit(repository)

    context = AnalysisUnitContextBuilder(
        repository_root=repository,
        token_budget=TokenBudget(
            system_prompt=10,
            task_prompt=20,
            source_context=500,
            output_reserve=100,
            hard_input_limit=1000,
        ),
        prompt_manifest_path=manifest,
    ).build(analysis_unit=unit, task_prompt="Extract facts.")

    assert [fragment.relative_path for fragment in context.selected_fragments] == [
        "package.json",
        ".env",
        "src/index.ts",
    ]
    assert context.omitted_fragments == ()
    assert context.messages[0].role == "system"
    assert context.messages[0].content == UNTRUSTED_SOURCE_GUARD
    assert "BEGIN UNTRUSTED SOURCE .env" in context.messages[1].content
    assert "secret-value" not in context.messages[1].content
    assert "[REDACTED:DOTENV_VALUE]" in context.messages[1].content
    assert "Bearer abc.def.ghi" not in context.messages[1].content
    assert "[REDACTED:AUTHORIZATION_HEADER]" in context.messages[1].content
    assert "    1 |" in context.messages[1].content
    assert "    2 | console.log('ok')" in context.messages[1].content
    assert context.metadata["redaction_event_count"] == 2


def test_context_builder_trims_to_budget_deterministically(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    write(repository / "package.json", '{"name":"payments"}')
    write(repository / "src" / "a.ts", "a" * 80)
    write(repository / "src" / "b.ts", "b" * 80)
    manifest = write_prompt_manifest(tmp_path)
    unit = make_unit(repository)

    context = AnalysisUnitContextBuilder(
        repository_root=repository,
        token_budget=TokenBudget(
            system_prompt=10,
            task_prompt=10,
            source_context=15,
            output_reserve=20,
            hard_input_limit=100,
        ),
        prompt_manifest_path=manifest,
    ).build(analysis_unit=unit, task_prompt="Extract facts.")

    assert [fragment.relative_path for fragment in context.selected_fragments] == ["package.json"]
    assert [fragment.relative_path for fragment in context.omitted_fragments] == [
        "src/a.ts",
        "src/b.ts",
    ]
    assert context.selected_tokens <= 30
    assert context.omitted_tokens > 0


def test_context_builder_includes_prompt_manifest_version_and_hash(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    write(repository / "package.json", '{"name":"payments"}')
    manifest = write_prompt_manifest(tmp_path, version="0.2.0")
    manifest_content = manifest.read_text(encoding="utf-8")

    context = AnalysisUnitContextBuilder(
        repository_root=repository,
        token_budget=TokenBudget(
            system_prompt=1,
            task_prompt=1,
            source_context=100,
            output_reserve=1,
            hard_input_limit=200,
        ),
        prompt_manifest_path=manifest,
    ).build(analysis_unit=make_unit(repository), task_prompt="Extract facts.")

    assert context.prompt_manifest.name == "component_analysis"
    assert context.prompt_manifest.version == "0.2.0"
    assert context.prompt_manifest.content_hash == sha256(
        manifest_content.encode("utf-8")
    ).hexdigest()
    assert context.metadata["prompt_version"] == "0.2.0"
    assert context.metadata["prompt_hash"] == context.prompt_manifest.content_hash


def make_unit(repository: Path) -> AnalysisUnit:
    relative_paths = tuple(
        path.relative_to(repository).as_posix()
        for path in sorted(repository.rglob("*"))
        if path.is_file()
    )
    return AnalysisUnit(
        unit_id="unit-root",
        root_paths=(".",),
        manifest_files=tuple(path for path in relative_paths if path == "package.json"),
        entry_points=tuple(path for path in relative_paths if path.endswith("index.ts")),
        config_files=tuple(path for path in relative_paths if path == ".env"),
        relevant_source_files=tuple(path for path in relative_paths if path.endswith(".ts")),
        candidate_name="payments",
        dependency_hints=("fastify",),
        token_estimate=100,
        file_hashes={path: sha256(path.encode("utf-8")).hexdigest() for path in relative_paths},
        signals=("PACKAGE_JSON",),
    )


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_prompt_manifest(tmp_path: Path, *, version: str = "0.1.0") -> Path:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"name": "component_analysis", "version": version, "files": []}),
        encoding="utf-8",
    )
    return manifest
