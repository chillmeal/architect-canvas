from __future__ import annotations

from pathlib import Path

from app.core.security import resolve_repository_child_path


class SafeFileReader:
    def __init__(self, repository_root: str | Path) -> None:
        self.repository_root = Path(repository_root)

    def read_text(self, relative_path: str | Path, *, encoding: str = "utf-8") -> str:
        safe_path = resolve_repository_child_path(self.repository_root, relative_path)
        if not safe_path.is_file():
            raise FileNotFoundError(f"Repository file not found: {relative_path}")
        return safe_path.read_text(encoding=encoding)
