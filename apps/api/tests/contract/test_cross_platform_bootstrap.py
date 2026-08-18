from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_linux_bootstrap_creates_local_venv_and_installs_workspace_dependencies() -> None:
    script = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")

    assert '"$PYTHON_BIN" -m venv "$ROOT_DIR/.venv"' in script
    assert '"$VENV_PYTHON" -m pip install -e "$ROOT_DIR/apps/api[dev]"' in script
    assert "npm install" in script
    assert "pip install -e" in script
    assert "python -m pip install -e" not in script


def test_makefile_uses_local_venv_for_backend_commands() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "ROOT_PYTHON ?= .venv/bin/python" in makefile
    assert "ROOT_PYTHON ?= .venv/Scripts/python.exe" in makefile
    assert "PYTHON ?= ../../.venv/bin/python" in makefile
    assert "PYTHON ?= ../../.venv/Scripts/python.exe" in makefile
    assert "$(PYTHON) -m pytest" in makefile
    assert "$(PYTHON) -m ruff check ." in makefile


def test_readme_documents_windows_linux_smoke_and_run_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Linux shell:" in readme
    assert "Windows PowerShell:" in readme
    assert "sh scripts/bootstrap.sh" in readme
    assert r".\.venv\Scripts\python.exe -m pip install -e" in readme
    assert "(cd apps/api && ../../.venv/bin/python -m pytest)" in readme
    assert r"..\..\.venv\Scripts\python.exe -m pytest" in readme
    assert "npm run lint:web" in readme
    assert "npm run typecheck:web" in readme
    assert "npm run test:web" in readme
    assert "npm run build:web" in readme
    assert "uvicorn app.main:app" in readme
