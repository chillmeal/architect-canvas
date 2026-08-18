# Manual GigaChat Smoke Test

Status: manual only  
Scope: real GigaChat provider checks outside CI  
Prerequisites: approved credentials, approved source-sharing policy, local `.env`

This smoke test verifies the real `GigaChatProvider` boundary. It must not run in CI and must not use production source repositories until the policy questions in `docs/ARCHITECTURE.md`, section 26, are answered.

## Safety Rules

- Store `GIGACHAT_CREDENTIALS` only in `.env`, shell environment, or an approved local secret store.
- Do not commit `.env`, access tokens, request bodies, raw prompts, or source fragments.
- Keep `LOG_SOURCE_CONTENT=false`.
- Keep `GIGACHAT_VERIFY_SSL_CERTS=true` unless using explicitly approved local TLS debugging.
- Run these checks against artificial fixture repositories or synthetic prompts.
- Redact terminal output before sharing logs.

## Environment

Windows PowerShell:

```powershell
$env:APP_ENV="local"
$env:GIGACHAT_CREDENTIALS="<base64-client-credentials>"
$env:GIGACHAT_SCOPE="GIGACHAT_API_CORP"
$env:GIGACHAT_BASE_URL="https://api.giga.chat/v1"
$env:GIGACHAT_AUTH_URL="https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
$env:GIGACHAT_MODEL_DISCOVERY="GigaChat"
$env:GIGACHAT_MODEL_ANALYSIS="GigaChat"
$env:GIGACHAT_MODEL_VALIDATION="GigaChat"
$env:LOG_SOURCE_CONTENT="false"
```

Linux shell:

```sh
export APP_ENV=local
export GIGACHAT_CREDENTIALS="<base64-client-credentials>"
export GIGACHAT_SCOPE=GIGACHAT_API_CORP
export GIGACHAT_BASE_URL=https://api.giga.chat/v1
export GIGACHAT_AUTH_URL=https://ngw.devices.sberbank.ru:9443/api/v2/oauth
export GIGACHAT_MODEL_DISCOVERY=GigaChat
export GIGACHAT_MODEL_ANALYSIS=GigaChat
export GIGACHAT_MODEL_VALIDATION=GigaChat
export LOG_SOURCE_CONTENT=false
```

## Preflight

Run automated fake-provider checks first:

```sh
cd apps/api
../../.venv/bin/python -m pytest tests/unit/test_gigachat_provider.py tests/unit/test_llm_budget_retry.py
../../.venv/bin/python -m ruff check .
```

Windows PowerShell:

```powershell
Push-Location apps\api
..\..\.venv\Scripts\python.exe -m pytest tests\unit\test_gigachat_provider.py tests\unit\test_llm_budget_retry.py
..\..\.venv\Scripts\python.exe -m ruff check .
Pop-Location
```

## OAuth

Goal: prove credentials exchange for an access token and that credentials are not logged.

Expected result:

- first provider call sends Basic credentials only to `/api/v2/oauth`;
- access token is cached in memory;
- terminal output and application logs do not contain `GIGACHAT_CREDENTIALS`, Basic credentials, or Bearer token values.

Failure handling:

- `401` or `403`: verify scope, project access, and credential encoding;
- TLS error: keep SSL verification enabled; install the approved GigaChat CA certificates or set `GIGACHAT_CA_BUNDLE_FILE` to the approved PEM bundle instead of disabling TLS.

## List Models

Goal: confirm the configured API project exposes usable models.

Expected result:

- `GET /models` returns at least one model;
- configured `GIGACHAT_MODEL_DISCOVERY`, `GIGACHAT_MODEL_ANALYSIS`, and `GIGACHAT_MODEL_VALIDATION` are present or intentionally mapped to available model IDs;
- health check reports `ok=true`.

Record only model IDs and timestamps in the smoke note. Do not record tokens or headers.

## Token Count

Goal: confirm `/tokens/count` works for synthetic messages.

Use a two-message synthetic input: a short system message and a short user message. Do not include real source code.

Expected result:

- token count returns a positive integer;
- result is stable enough for budget planning;
- no prompt body is logged.

## Structured Response

Goal: confirm strict JSON Schema call succeeds.

Use a synthetic `CandidateFact` request with:

- system message first;
- `response_format.type=json_schema`;
- `strict=true`;
- artificial evidence path such as `src/main.py`;
- no real source fragments.

Expected result:

- response parses as `CandidateFact`;
- usage metadata has prompt/completion/total tokens when returned by the provider;
- finish reason is publishable, for example `stop`;
- raw response body is not written to logs.

## Invalid Schema Behavior

Goal: confirm invalid model output does not enter the analysis pipeline.

Manual method:

- run a local fake transport or controlled provider test that returns malformed JSON once and valid JSON once;
- then run a case that returns schema-invalid JSON twice.

Expected result:

- malformed JSON triggers exactly one repair call;
- repair success returns a typed result;
- repair failure returns provider error `INVALID_RESPONSE`;
- regex fallback is not used;
- candidate store and graph assembler receive no invalid fact.

## 413 Re-Chunk

Goal: confirm payload-too-large handling remains deterministic.

Manual method:

- use fake transport or a safe synthetic oversized prompt;
- never use real source files just to trigger size errors.

Expected result:

- HTTP `413` maps to `PAYLOAD_TOO_LARGE`;
- retry planning allows one smaller-context attempt;
- context is reduced through the token budget planner, not by arbitrary string truncation;
- the second attempt still respects bounded concurrency.

## Rate Limit Behavior

Goal: confirm rate-limit handling follows the retry policy.

Manual method:

- use fake transport to return `429`;
- only test the real endpoint if rate-limit testing is approved for the API project.

Expected result:

- HTTP `429` maps to `RATE_LIMITED`;
- retry policy uses bounded retry count and backoff;
- retries do not bypass the provider semaphore;
- final failure state is explicit if retries are exhausted.

## Token Refresh

Goal: confirm cached access token is refreshed safely.

Expected result:

- token refresh occurs before expiry using the configured skew;
- a `401` API response clears the cached token and retries OAuth once;
- a second `401` fails with `UNAUTHORIZED`;
- no expired or fresh token value appears in logs.

## CI Policy

Real-provider smoke tests are skipped in CI. CI must run only fake-provider automated tests:

```sh
cd apps/api
../../.venv/bin/python -m pytest tests/unit/test_gigachat_provider.py tests/unit/test_llm_provider.py tests/unit/test_llm_budget_retry.py
```

If a manual smoke test fails, do not mark CI as failed solely because real credentials or rate limits were unavailable. Open a task with:

- date and local environment;
- sanitized model IDs;
- sanitized error code;
- affected smoke section;
- no credentials, tokens, prompts, source fragments, or raw provider payloads.
