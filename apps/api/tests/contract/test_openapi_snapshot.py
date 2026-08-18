import json
import subprocess
import sys
from pathlib import Path

from app.core.config import AppConfig
from app.main import create_app

ROOT = Path(__file__).resolve().parents[4]
SNAPSHOT_PATH = ROOT / "contracts" / "openapi.snapshot.json"
CLIENT_PATH = ROOT / "apps" / "web" / "src" / "api" / "generated" / "client.ts"


def test_openapi_snapshot_matches_fastapi_contract() -> None:
    app = create_app(AppConfig(app_env="test", database_url="sqlite:///:memory:"))
    current_openapi = json.dumps(
        app.openapi(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )

    assert SNAPSHOT_PATH.read_text(encoding="utf-8") == current_openapi + "\n"


def test_generated_frontend_client_matches_openapi_snapshot() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_ts_client.py"), "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert CLIENT_PATH.is_file()
