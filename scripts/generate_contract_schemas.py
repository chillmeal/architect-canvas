from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.contracts.graph import Evidence, GraphSnapshot  # noqa: E402


SCHEMAS = {
    "graph.schema.json": GraphSnapshot,
    "evidence.schema.json": Evidence,
}


def main() -> None:
    contracts_dir = REPOSITORY_ROOT / "contracts"
    contracts_dir.mkdir(exist_ok=True)
    for file_name, model in SCHEMAS.items():
        schema = model.model_json_schema(by_alias=True)
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://architecture-visualizer.local/contracts/{file_name}"
        target_path = contracts_dir / file_name
        target_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
