# Architecture Visualizer

Local MVP for auditing a repository and building a versioned architecture graph.

The main architecture contract is [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Manual real-provider checks are documented in [docs/GIGACHAT_SMOKE_TEST.md](docs/GIGACHAT_SMOKE_TEST.md).

## Applications

- `apps/api` — FastAPI backend, audit orchestration, validation, persistence, and LLM provider boundary.
- `apps/web` — React frontend for project setup, audit progress, graph viewing, and manual revisions.

## Bootstrap Goal

Phase 0 keeps the system intentionally small: both applications expose basic health checks and the repository contains the target structure, documentation, contracts, and test placeholders needed for later MVP phases.

## Prerequisites

- Python 3.11+
- Node.js 20+
- npm 10+

No global pytest, ruff, formatter, or frontend build tool is required. Backend developer tools are installed into the local `.venv`; frontend tools are installed through npm workspaces.

## Setup

Linux shell:

```sh
sh scripts/bootstrap.sh
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".\apps\api[dev]"
npm install
```

Create the local environment file before starting the API:

```sh
cp .env.example .env
```

At minimum set:

```dotenv
GIGACHAT_CREDENTIALS=<your credentials>
REPOSITORY_ALLOWED_ROOTS=/absolute/path/to/parent/directory/with/repos
```

On Windows, `REPOSITORY_ALLOWED_ROOTS` can be a normal absolute path such as `C:\work\repos`. Multiple allowed roots are separated by `;`. The three `GIGACHAT_MODEL_*` values may stay empty: the audit pipeline resolves an available chat model through `/models`. Keep `GIGACHAT_AUTH_URL=https://ngw.devices.sberbank.ru:9443/api/v2/oauth` unless your approved corporate gateway explicitly provides another OAuth endpoint. If Python reports a certificate verification error, set `GIGACHAT_CA_BUNDLE_FILE` to the approved CA bundle instead of disabling TLS verification.

Keep real credentials only in `.env` or another local secret store. `.env` is ignored by Git. For the MVP, run the API natively when auditing host repositories; Docker requires those repository directories to be mounted into the container explicitly.

## Generated Contracts

OpenAPI is generated from FastAPI/Pydantic and the TypeScript client is generated from `contracts/openapi.snapshot.json`.

Linux shell:

```sh
sh scripts/generate-api-client.sh
.venv/bin/python scripts/generate_openapi_snapshot.py --check
.venv/bin/python scripts/generate_ts_client.py --check
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts\generate_openapi_snapshot.py
.\.venv\Scripts\python.exe scripts\generate_ts_client.py
.\.venv\Scripts\python.exe scripts\generate_openapi_snapshot.py --check
.\.venv\Scripts\python.exe scripts\generate_ts_client.py --check
```

## Smoke Checklist

Linux shell:

```sh
(cd apps/api && ../../.venv/bin/python -m pytest)
(cd apps/api && ../../.venv/bin/python -m ruff check .)
(cd apps/api && ../../.venv/bin/python -m alembic upgrade head)
npm run lint:web
npm run typecheck:web
npm run test:web
npm run build:web
```

Windows PowerShell:

```powershell
Push-Location apps\api
..\..\.venv\Scripts\python.exe -m pytest
..\..\.venv\Scripts\python.exe -m ruff check .
..\..\.venv\Scripts\python.exe -m alembic upgrade head
Pop-Location
npm run lint:web
npm run typecheck:web
npm run test:web
npm run build:web
```

Initialize/update the local database before the first run:

```sh
cd apps/api
../../.venv/bin/python -m alembic upgrade head
```

Windows PowerShell:

```powershell
Push-Location apps\api
..\..\.venv\Scripts\python.exe -m alembic upgrade head
Pop-Location
```

Run the API from the repository root so `.env` and the default SQLite path resolve consistently:

```sh
.venv/bin/python -m uvicorn app.main:app --app-dir apps/api --reload --host 127.0.0.1 --port 8000 --env-file .env
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir apps\api --reload --host 127.0.0.1 --port 8000 --env-file .env
```

Run the web app:

```sh
npm run dev:web
```
