from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
SNAPSHOT_PATH = ROOT / "contracts" / "openapi.snapshot.json"

sys.path.insert(0, str(API_ROOT))

from app.core.config import AppConfig  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or check OpenAPI snapshot.")
    parser.add_argument("--check", action="store_true", help="Fail if snapshot is out of date.")
    args = parser.parse_args()

    snapshot = generate_snapshot()
    rendered = render_json(snapshot)
    if args.check:
        current = SNAPSHOT_PATH.read_text(encoding="utf-8") if SNAPSHOT_PATH.exists() else ""
        if current != rendered:
            print("contracts/openapi.snapshot.json is out of date", file=sys.stderr)
            return 1
        return 0

    SNAPSHOT_PATH.write_text(rendered, encoding="utf-8")
    return 0


def generate_snapshot() -> dict[str, object]:
    app = create_app(AppConfig(app_env="test", database_url="sqlite:///:memory:"))
    return app.openapi()


def render_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
