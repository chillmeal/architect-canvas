from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import PurePosixPath

SYSTEM_DENY_DIRECTORIES = frozenset(
    {
        ".git",
        ".idea",
        ".vscode",
        "node_modules",
        "dist",
        "build",
        "target",
        "coverage",
        "__pycache__",
    }
)

ARCHIVE_EXTENSIONS = frozenset(
    {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war"}
)
IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tiff"}
)
LOCKFILE_NAMES = frozenset(
    {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock"}
)
GENERATED_CLIENT_MARKERS = ("generated", "openapi", "swagger")


@dataclass(frozen=True)
class IgnoreRule:
    pattern: str
    negated: bool
    directory_only: bool
    anchored: bool


class RepositoryIgnoreRules:
    def __init__(self, rules: tuple[IgnoreRule, ...] = ()) -> None:
        self.rules = rules

    @classmethod
    def parse(cls, content: str) -> "RepositoryIgnoreRules":
        rules: list[IgnoreRule] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            if negated:
                line = line[1:].strip()
            if not line:
                continue
            directory_only = line.endswith("/")
            line = line.rstrip("/")
            anchored = line.startswith("/")
            line = line.lstrip("/")
            rules.append(
                IgnoreRule(
                    pattern=line,
                    negated=negated,
                    directory_only=directory_only,
                    anchored=anchored,
                )
            )
        return cls(tuple(rules))

    def is_ignored(self, relative_path: str, *, is_dir: bool = False) -> bool:
        normalized = _normalize_relative_path(relative_path)
        ignored = False
        for rule in self.rules:
            if rule.directory_only and not is_dir:
                continue
            if _matches_rule(normalized, rule):
                ignored = not rule.negated
        return ignored


def system_exclusion_reason(relative_path: str, *, is_dir: bool = False) -> str | None:
    normalized = _normalize_relative_path(relative_path)
    path = PurePosixPath(normalized)
    parts = path.parts
    if any(part in SYSTEM_DENY_DIRECTORIES for part in parts):
        return "SYSTEM_DENY_DIRECTORY"
    if is_dir:
        return None
    suffix = path.suffix.lower()
    name = path.name
    if suffix in ARCHIVE_EXTENSIONS:
        return "ARCHIVE"
    if suffix in IMAGE_EXTENSIONS:
        return "IMAGE"
    if name in LOCKFILE_NAMES:
        return "LOCKFILE"
    if name.endswith((".min.js", ".min.css")):
        return "MINIFIED"
    lower_path = normalized.lower()
    if any(marker in lower_path for marker in GENERATED_CLIENT_MARKERS) and (
        lower_path.endswith((".ts", ".js", ".py"))
    ):
        return "GENERATED_CLIENT"
    return None


def _matches_rule(relative_path: str, rule: IgnoreRule) -> bool:
    path = PurePosixPath(relative_path)
    if rule.anchored or "/" in rule.pattern:
        return fnmatch(relative_path, rule.pattern)
    return any(fnmatch(part, rule.pattern) for part in path.parts)


def _normalize_relative_path(relative_path: str) -> str:
    return PurePosixPath(relative_path.replace("\\", "/")).as_posix()
