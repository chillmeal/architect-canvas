from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.domain.enums import NodeType

_SEPARATOR_PATTERN = re.compile(r"[\s\\/:]+")
_TOKEN_PATTERN = re.compile(r"[^\w._-]+")
ROOT_OWNER_PATH = "_root"


class StableLogicalKeyError(ValueError):
    pass


@dataclass(frozen=True)
class StableLogicalKeySource:
    project_id: str
    node_type: NodeType
    owner_path: tuple[str, ...]
    name: str
    artifact_id: str | None = None
    package_name: str | None = None
    deployment_name: str | None = None
    repository_path: str | None = None


@dataclass(frozen=True)
class StableLogicalKey:
    value: str

    @classmethod
    def from_source(cls, source: StableLogicalKeySource) -> StableLogicalKey:
        project_id = normalize_key_part(source.project_id)
        owner_path = normalize_owner_path(source.owner_path)
        if not normalize_key_part(source.name):
            raise StableLogicalKeyError("name is required")
        logical_name = _build_logical_name(source)
        if not project_id:
            raise StableLogicalKeyError("project_id is required")
        if not owner_path:
            owner_path = ROOT_OWNER_PATH
        if not logical_name:
            raise StableLogicalKeyError("name is required")
        return cls(f"{project_id}/{source.node_type.value}/{owner_path}/{logical_name}")


def normalize_key_part(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = _SEPARATOR_PATTERN.sub("-", normalized)
    normalized = _TOKEN_PATTERN.sub("", normalized)
    return normalized.strip("-._")


def normalize_owner_path(parts: tuple[str, ...]) -> str:
    normalized_parts = [normalize_key_part(part) for part in parts]
    filtered_parts = [part for part in normalized_parts if part]
    return "/".join(filtered_parts)


def _build_logical_name(source: StableLogicalKeySource) -> str:
    name = normalize_key_part(source.name)
    qualifiers = []
    for prefix, value in (
        ("artifact", source.artifact_id),
        ("package", source.package_name),
        ("deployment", source.deployment_name),
        ("path", _normalize_repository_path(source.repository_path)),
    ):
        if value:
            normalized_value = normalize_key_part(value)
            if normalized_value:
                qualifiers.append(f"{prefix}-{normalized_value}")
    if not qualifiers:
        raise StableLogicalKeyError(
            "stable logical key requires at least one identity signal besides display name"
        )
    return "__".join([name, *sorted(qualifiers)])


def _normalize_repository_path(value: str | None) -> str | None:
    if not value:
        return None
    normalized = str(PurePosixPath(value.replace("\\", "/")))
    return normalized.strip(".") or "root"
