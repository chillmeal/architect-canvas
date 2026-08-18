# Tomorrow Runbook — Local MVP

Use this sequence on the work laptop. The supported MVP mode is **native backend + Vite frontend on the same machine as the repository**.

## 1. Prerequisites

- Python 3.11+
- Node.js 20+
- npm 10+
- Git
- A valid GigaChat authorization key and the matching scope (`GIGACHAT_API_CORP`, `GIGACHAT_API_B2B`, or `GIGACHAT_API_PERS`)
- GigaChat/Ministry CA certificates trusted by Python, or an approved PEM bundle path

Do not use Docker for the first real audit unless the source repository is explicitly mounted into the container.

## 2. Install dependencies

Linux:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e './apps/api[dev]'
npm install
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e '.\apps\api[dev]'
npm install
```

If the corporate network blocks PyPI/npm, use the approved internal package mirrors. This is an environment prerequisite, not an application fallback.

## 3. Configure `.env`

Copy `.env.example` to `.env` and set at least:

```dotenv
GIGACHAT_CREDENTIALS=<authorization key>
GIGACHAT_SCOPE=GIGACHAT_API_CORP
GIGACHAT_BASE_URL=https://api.giga.chat/v1
GIGACHAT_AUTH_URL=https://ngw.devices.sberbank.ru:9443/api/v2/oauth
REPOSITORY_ALLOWED_ROOTS=/absolute/path/to/directory/containing/repos
```

The scope must match the authorization key. `REPOSITORY_ALLOWED_ROOTS` may be the repository itself or one of its parent directories. Multiple roots are separated by `;`.

If Python reports `CERTIFICATE_VERIFY_FAILED`, keep TLS verification enabled and set:

```dotenv
GIGACHAT_CA_BUNDLE_FILE=/approved/path/russian_trusted_root_ca_pem.crt
```

The three `GIGACHAT_MODEL_*` values can stay empty; the app resolves an available model via `/models`.

## 4. Initialize the database

Linux:

```sh
(cd apps/api && ../../.venv/bin/python -m alembic upgrade head)
```

Windows PowerShell:

```powershell
Push-Location apps\api
..\..\.venv\Scripts\python.exe -m alembic upgrade head
Pop-Location
```

## 5. Start backend

From the repository root:

Linux:

```sh
.venv/bin/python -m uvicorn app.main:app --app-dir apps/api --reload --host 127.0.0.1 --port 8000 --env-file .env
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir apps\api --reload --host 127.0.0.1 --port 8000 --env-file .env
```

Check `http://127.0.0.1:8000/api/v1/health`. Expected response contains `"status":"ok"`.

If Windows returns `WinError 10013` for port `8000`, do not change source code. Set
`APP_PORT=8010` in the root `.env` and start Uvicorn with `--port 8010`. The Vite
proxy reads `APP_HOST`/`APP_PORT` from the same root `.env`, so frontend requests
will follow the new backend port automatically.

## 6. Start frontend

In a second terminal from the repository root:

```sh
npm run dev:web
```

Open the Vite URL printed in the terminal.

## 7. First real audit

1. Open **Провести аудит**.
2. Choose repository and paste its **absolute path**.
3. Repository preflight must succeed. It checks path safety, Git metadata, SQLite write access, and GigaChat `/models` availability.
4. Click **Запустить аудит**.
5. Wait for terminal status.
6. `COMPLETED` or `COMPLETED_WITH_WARNINGS` must load a graph snapshot onto the canvas.

For the first run, prefer a small representative repository or one functional subsystem. A very large monorepo can generate many LLM calls and makes provider/configuration problems harder to diagnose.

## 8. Expected canvas behavior

- Edges are neutral gray by default.
- Selecting a node highlights only its related edges in green.
- Selecting an edge highlights the complete line and arrowhead in yellow.
- Only the two connector ports used by the selected edge are highlighted.
- Dragging empty canvas pans in both axes.
- Regular mouse wheel zooms around the cursor; `Shift` + wheel pans horizontally.
- Canvas drag remains the primary pan gesture in both axes.
- Edge endpoints use the exact center of the visible node ports.

## 9. If it fails

- **Repository path rejected** → verify absolute path and `REPOSITORY_ALLOWED_ROOTS`.
- **Git metadata error** → use a Git repository, or explicitly set `AUDIT_ALLOW_NON_GIT=true` only if intended.
- **401/403 GigaChat** → verify authorization key and `GIGACHAT_SCOPE`.
- **OAuth host error** → keep the documented `GIGACHAT_AUTH_URL` unless your approved gateway says otherwise.
- **Certificate verify error** → install the approved CA certificate or set `GIGACHAT_CA_BUNDLE_FILE`; do not disable TLS for the work run.
- **Audit FAILED** → the UI now keeps the actual pipeline error visible instead of attempting to load a nonexistent graph.
- **COMPLETED_WITH_WARNINGS but sparse graph** → inspect audit summary/warnings; the MVP intentionally prefers missing facts over invented architecture.
