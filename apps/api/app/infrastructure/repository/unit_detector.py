from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from xml.etree import ElementTree

from app.infrastructure.repository.file_reader import SafeFileReader
from app.infrastructure.repository.scanner import (
    FileIndexRecord,
    FileIndexStatus,
    RepositoryFileIndex,
)


@dataclass(frozen=True)
class AnalysisUnit:
    unit_id: str
    root_paths: tuple[str, ...]
    manifest_files: tuple[str, ...]
    entry_points: tuple[str, ...]
    config_files: tuple[str, ...]
    relevant_source_files: tuple[str, ...]
    candidate_name: str
    dependency_hints: tuple[str, ...]
    token_estimate: int
    file_hashes: dict[str, str]
    signals: tuple[str, ...]


@dataclass(frozen=True)
class UnitSignal:
    root_path: str
    relative_path: str
    signal_type: str


class AnalysisUnitDetector:
    def __init__(self, repository_root) -> None:
        self.reader = SafeFileReader(repository_root)

    def detect(self, file_index: RepositoryFileIndex) -> tuple[AnalysisUnit, ...]:
        files = tuple(record for record in file_index.files if record.status == FileIndexStatus.INDEXED)
        signals = self._detect_signals(files)
        if not signals:
            signals = self._fallback_directory_signals(files)
        root_signals = tuple(_first_signal_per_root(signals))
        units = tuple(self._build_unit(signal, files, signals) for signal in root_signals)
        return tuple(sorted(units, key=lambda unit: unit.unit_id))

    def _detect_signals(self, files: tuple[FileIndexRecord, ...]) -> tuple[UnitSignal, ...]:
        signals: list[UnitSignal] = []
        seen_roots: set[str] = set()
        for record in files:
            signal_type = _signal_type(record.relative_path)
            if signal_type is None:
                continue
            root_path = _unit_root_for_signal(record.relative_path, signal_type)
            key = f"{root_path}:{signal_type}"
            if key in seen_roots:
                continue
            seen_roots.add(key)
            signals.append(
                UnitSignal(
                    root_path=root_path,
                    relative_path=record.relative_path,
                    signal_type=signal_type,
                )
            )
        return tuple(signals)

    def _fallback_directory_signals(
        self,
        files: tuple[FileIndexRecord, ...],
    ) -> tuple[UnitSignal, ...]:
        roots = sorted({_fallback_root(record.relative_path) for record in files})
        return tuple(
            UnitSignal(root_path=root, relative_path=root, signal_type="FALLBACK_DIRECTORY")
            for root in roots
            if root
        )

    def _build_unit(
        self,
        signal: UnitSignal,
        files: tuple[FileIndexRecord, ...],
        all_signals: tuple[UnitSignal, ...],
    ) -> AnalysisUnit:
        root_files = tuple(record for record in files if _is_under_root(record.relative_path, signal.root_path))
        manifests = tuple(
            sorted(
                record.relative_path
                for record in root_files
                if _signal_type(record.relative_path) in MANIFEST_SIGNAL_TYPES
            )
        )
        config_files = tuple(
            sorted(record.relative_path for record in root_files if _is_config_file(record.relative_path))
        )
        source_files = tuple(
            sorted(record.relative_path for record in root_files if _is_source_file(record.relative_path))
        )
        entry_points = tuple(path for path in source_files if _is_entry_point(path))
        file_hashes = {record.relative_path: record.sha256 for record in root_files}
        root_signals = tuple(
            sorted(item.signal_type for item in all_signals if item.root_path == signal.root_path)
        )
        dependency_hints = tuple(sorted(self._dependency_hints(manifests + config_files)))
        return AnalysisUnit(
            unit_id=_unit_id(signal.root_path),
            root_paths=(signal.root_path,),
            manifest_files=manifests,
            entry_points=entry_points,
            config_files=config_files,
            relevant_source_files=source_files,
            candidate_name=self._candidate_name(signal.root_path, manifests),
            dependency_hints=dependency_hints,
            token_estimate=sum(_estimate_tokens(record.size_bytes) for record in root_files),
            file_hashes=file_hashes,
            signals=root_signals or (signal.signal_type,),
        )

    def _candidate_name(self, root_path: str, manifest_files: tuple[str, ...]) -> str:
        for manifest in manifest_files:
            if manifest.endswith("package.json"):
                name = self._package_name(manifest)
                if name:
                    return name
            if manifest.endswith("pom.xml"):
                name = self._pom_artifact_id(manifest)
                if name:
                    return name
        return PurePosixPath(root_path).name or "repository"

    def _dependency_hints(self, candidate_files: tuple[str, ...]) -> set[str]:
        hints: set[str] = set()
        for relative_path in candidate_files:
            if relative_path.endswith("package.json"):
                hints.update(self._package_dependencies(relative_path))
            elif relative_path.endswith("pom.xml"):
                hints.update(self._pom_dependencies(relative_path))
            elif relative_path.endswith((".gradle", ".gradle.kts")):
                hints.update(self._gradle_dependencies(relative_path))
            elif _is_config_file(relative_path):
                hints.add(PurePosixPath(relative_path).name)
        return hints

    def _package_name(self, relative_path: str) -> str | None:
        try:
            payload = json.loads(self.reader.read_text(relative_path))
        except (OSError, json.JSONDecodeError):
            return None
        name = payload.get("name")
        return str(name) if name else None

    def _package_dependencies(self, relative_path: str) -> set[str]:
        try:
            payload = json.loads(self.reader.read_text(relative_path))
        except (OSError, json.JSONDecodeError):
            return set()
        hints: set[str] = set()
        for field in ("dependencies", "devDependencies", "peerDependencies"):
            dependencies = payload.get(field)
            if isinstance(dependencies, dict):
                hints.update(str(name) for name in dependencies)
        return hints

    def _pom_artifact_id(self, relative_path: str) -> str | None:
        try:
            root = ElementTree.fromstring(self.reader.read_text(relative_path))
        except (OSError, ElementTree.ParseError):
            return None
        for child in root:
            if _xml_local_name(child.tag) == "artifactId" and child.text:
                return child.text.strip()
        return None

    def _pom_dependencies(self, relative_path: str) -> set[str]:
        try:
            root = ElementTree.fromstring(self.reader.read_text(relative_path))
        except (OSError, ElementTree.ParseError):
            return set()
        hints: set[str] = set()
        for element in root.iter():
            if _xml_local_name(element.tag) == "artifactId" and element.text:
                hints.add(element.text.strip())
        return hints

    def _gradle_dependencies(self, relative_path: str) -> set[str]:
        try:
            content = self.reader.read_text(relative_path)
        except OSError:
            return set()
        return set(re.findall(r"['\"]([A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:[^'\"]+)['\"]", content))


MANIFEST_SIGNAL_TYPES = frozenset(
    {
        "POM",
        "GRADLE",
        "PACKAGE_JSON",
        "DOCKERFILE",
        "HELM_CHART",
        "DEPLOYMENT_MANIFEST",
        "OPENAPI",
    }
)

SOURCE_EXTENSIONS = frozenset(
    {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".go", ".cs", ".php", ".rs"}
)
CONFIG_NAMES = frozenset(
    {
        "application.yml",
        "application.yaml",
        "application.properties",
        "appsettings.json",
        "config.yml",
        "config.yaml",
    }
)
ENTRY_POINT_NAMES = frozenset(
    {
        "main.py",
        "app.py",
        "index.js",
        "index.ts",
        "server.js",
        "server.ts",
        "Application.java",
        "main.go",
        "Program.cs",
    }
)


def _signal_type(relative_path: str) -> str | None:
    path = PurePosixPath(relative_path)
    name = path.name
    lower_name = name.lower()
    if name == "pom.xml":
        return "POM"
    if lower_name in {"build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"}:
        return "GRADLE"
    if name == "package.json":
        return "PACKAGE_JSON"
    if name == "Dockerfile" or lower_name.startswith("dockerfile."):
        return "DOCKERFILE"
    if name == "Chart.yaml":
        return "HELM_CHART"
    if _is_deployment_manifest(relative_path):
        return "DEPLOYMENT_MANIFEST"
    if _is_openapi_file(relative_path):
        return "OPENAPI"
    if _is_config_file(relative_path):
        return "APPLICATION_CONFIG"
    return None


def _unit_root_for_signal(relative_path: str, signal_type: str) -> str:
    path = PurePosixPath(relative_path)
    if signal_type == "HELM_CHART" and path.parent.name == "templates":
        return path.parent.parent.as_posix() or "."
    if signal_type == "APPLICATION_CONFIG" and "src" in path.parts:
        src_index = path.parts.index("src")
        if src_index > 0:
            return PurePosixPath(*path.parts[:src_index]).as_posix()
        return "."
    return path.parent.as_posix() or "."


def _is_deployment_manifest(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    lower_name = path.name.lower()
    if lower_name in {"deployment.yaml", "deployment.yml"}:
        return True
    return "deploy" in path.parts and path.suffix.lower() in {".yaml", ".yml"}


def _is_openapi_file(relative_path: str) -> bool:
    name = PurePosixPath(relative_path).name.lower()
    return name in {"openapi.yaml", "openapi.yml", "swagger.yaml", "swagger.yml", "openapi.json"}


def _is_config_file(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    return path.name in CONFIG_NAMES or path.name.startswith(".env")


def _is_source_file(relative_path: str) -> bool:
    return PurePosixPath(relative_path).suffix.lower() in SOURCE_EXTENSIONS


def _is_entry_point(relative_path: str) -> bool:
    return PurePosixPath(relative_path).name in ENTRY_POINT_NAMES


def _fallback_root(relative_path: str) -> str:
    parts = PurePosixPath(relative_path).parts
    if len(parts) >= 2:
        return PurePosixPath(parts[0], parts[1]).as_posix()
    return parts[0] if parts else "."


def _is_under_root(relative_path: str, root_path: str) -> bool:
    if root_path == ".":
        return True
    return relative_path == root_path or relative_path.startswith(f"{root_path}/")


def _unit_id(root_path: str) -> str:
    normalized = root_path.strip("./").replace("/", "-").replace("\\", "-")
    return f"unit-{normalized or 'root'}"


def _estimate_tokens(size_bytes: int) -> int:
    return max(1, size_bytes // 4)


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _first_signal_per_root(signals: tuple[UnitSignal, ...]) -> tuple[UnitSignal, ...]:
    first_by_root: dict[str, UnitSignal] = {}
    for signal in signals:
        first_by_root.setdefault(signal.root_path, signal)
    return tuple(first_by_root[root] for root in sorted(first_by_root))
