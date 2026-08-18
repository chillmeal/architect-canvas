# Architecture Visualizer — рабочее ТЗ и backlog задач

Статус документа: Draft 0.1  
Дата: 2026-08-18  
Источник архитектуры: `docs/ARCHITECTURE.md`  
Фокус ближайших работ: backend-first MVP, переносимый между Windows и Linux

---

## 1. Правила выполнения задач

### 1.1. Статусы

| Статус | Значение |
| --- | --- |
| TODO | Задача готова к взятию в работу или ожидает зависимость |
| IN_PROGRESS | Задача выполняется сейчас |
| DONE | Критерии приемки выполнены, проверки пройдены |
| BLOCKED | Есть внешний блокер или архитектурный конфликт |

### 1.2. Общий Definition of Done для каждой задачи

- Реализация не расходится с `docs/ARCHITECTURE.md`; при расхождении создан ADR.
- Изменения минимальны и не затрагивают несвязанные области.
- Контракты, схемы, миграции и документация обновлены, если изменилось поведение.
- Добавлены unit tests для доменной логики и integration/contract tests для границ.
- Проверки затронутой области проходят локально на Windows и не используют platform-specific hacks.
- Код не требует реальной сети, credentials или рабочего репозитория в автоматических тестах.
- Нет прямого вызова GigaChat из frontend или domain layer.
- Не добавлены экспериментальные или слабо поддерживаемые production dependencies.

### 1.3. Технические ограничения для переносимости

- Backend поддерживает Python 3.11+ и Linux как целевую рабочую среду.
- Для файловых путей использовать `pathlib`, `os.path.realpath`, явную нормализацию и тесты под path traversal.
- Shell-скрипты должны быть POSIX-compatible; PowerShell допустим только для локальной диагностики, не как основной workflow.
- SQLite используется через миграции Alembic; ручное изменение БД запрещено.
- Сетевые интеграции закрываются интерфейсами и fake-реализациями.
- Новые зависимости добавляются только при понятной необходимости и с объяснением в задаче или ADR.

---

## 2. Epic B0. Backend foundation

### B0-01. Конфигурация backend

Статус: DONE  
Зависимости: текущий bootstrap

Сделать строгую загрузку и валидацию backend config из environment.

Критерии приемки:

- `AppConfig` покрывает значения из `.env.example`: app, database, repository allowlist, GigaChat, audit limits, logging.
- Некорректные числовые значения, пустые production-sensitive значения и небезопасные debug flags дают понятную ошибку startup/preflight.
- Секреты не выводятся в `repr`, логах и ошибках.
- Есть unit tests на defaults, override через env, invalid values и secret masking.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B0-02. Единый формат ошибок и request id

Статус: DONE  
Зависимости: B0-01

Ввести стабильный формат HTTP-ошибок и request id middleware.

Критерии приемки:

- Каждый ответ API содержит или пробрасывает `X-Request-ID`.
- Ошибки имеют `error_code`, `message`, `request_id`, опционально `details`.
- Неожиданные исключения не раскрывают stack trace и secrets клиенту.
- Health endpoint продолжает работать.
- Есть integration tests на success, validation error и unhandled error.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B0-03. Structured logging

Статус: DONE  
Зависимости: B0-01, B0-02

Настроить JSON/logfmt structured logs без исходников и секретов.

Критерии приемки:

- Логи содержат `request_id`, `stage`, `project_id`, `audit_id`, `unit_id`, `duration`, `status`, `error_code` там, где они известны.
- GigaChat credentials, access token, source fragments и raw prompts не логируются.
- Уровень логирования управляется `LOG_LEVEL`.
- Есть unit tests на redaction formatter/filter.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

---

## 3. Epic B1. Domain contracts

### B1-01. Доменные enum и value objects

Статус: DONE  
Зависимости: B0-01

Зафиксировать типы узлов, связей, validation states, audit statuses, origins, override operations и reason codes.

Критерии приемки:

- Enums соответствуют `docs/ARCHITECTURE.md`, разделам 7, 9, 11 и 14.
- Unknown enum values в API/contract слоях обрабатываются явно, а не молча.
- Stable logical key строится не только из display name.
- Есть unit tests на enum coverage, stable key normalization и конфликтные входы.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B1-02. Pydantic-модели graph, evidence и validation record

Статус: DONE  
Зависимости: B1-01

Описать backend contracts для graph snapshot, node, edge, evidence, candidate fact, validation result и issue.

Критерии приемки:

- Evidence содержит relative path, file hash, line range, fragment hash/source fragment marker, source type, strength, analysis unit id и optional LLM invocation id.
- Inferred node/edge невалиден без evidence.
- JSON Schema генерируется из Pydantic-моделей и синхронизируется с `contracts/*.schema.json`.
- `additionalProperties` запрещен там, где контракт стабилен.
- Есть contract tests на schema generation и invalid payload rejection.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B1-03. Confidence policy

Статус: DONE  
Зависимости: B1-01, B1-02

Реализовать deterministic policy вычисления final validation state и confidence.

Критерии приемки:

- Модель не может задавать финальный confidence напрямую.
- Пороговые значения берутся из config и имеют безопасные defaults: confirmed >= 0.85, warnings 0.70-0.84, review 0.40-0.69.
- Hard invariant/evidence failure имеет приоритет над LLM-validator.
- Есть unit tests на все правила из раздела 11.9 архитектуры.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

---

## 4. Epic B2. Persistence and migrations

### B2-01. SQLite session и Alembic baseline

Статус: DONE  
Зависимости: B0-01, B1-01

Настроить SQLite storage с Alembic migrations.

Критерии приемки:

- SQLite работает в WAL mode, foreign keys включены.
- Таблицы создаются только через migration.
- Session lifecycle не хранит бизнес-правила.
- `var/data` не коммитится, кроме `.gitkeep`.
- Есть integration test на миграцию в temporary database.

Проверки:

- `python -m pytest`
- `python -m ruff check .`
- `alembic upgrade head`

### B2-02. Модель хранения audits и events

Статус: DONE  
Зависимости: B2-01

Добавить таблицы и repositories для Project, RepositoryState, Audit, AuditStage, AuditEvent.

Критерии приемки:

- Audit terminal states после завершения не переписываются.
- AuditEvent записывается короткой транзакцией и поддерживает пагинацию.
- Dirty repository state сохраняется как metadata, а не блокируется без policy.
- Есть tests на state persistence, event ordering и terminal immutability.

Проверки:

- `python -m pytest`
- `python -m ruff check .`
- `alembic upgrade head`

### B2-03. Модель хранения graph snapshots и revisions

Статус: TODO  
Зависимости: B2-02, B1-02

Добавить таблицы GraphSnapshot, GraphNode, GraphEdge, GraphRevision, GraphOverride.

Критерии приемки:

- GraphSnapshot после публикации неизменяем на уровне service/repository contract.
- Suppression inferred entity не удаляет historical record.
- Manual unsaved node можно удалить физически только до сохранения revision.
- Есть tests на immutable snapshot, suppression override и один active parent.

Проверки:

- `python -m pytest`
- `python -m ruff check .`
- `alembic upgrade head`

---

## 5. Epic B3. Repository scanner

### B3-01. Path safety

Статус: TODO  
Зависимости: B0-01

Реализовать проверку repository path и безопасный file access.

Критерии приемки:

- Path canonicalized через realpath и обязан находиться внутри `REPOSITORY_ALLOWED_ROOTS`.
- Запрещены filesystem root, home без allowlist, path traversal и symlink escape.
- Broken symlink дает warning, а не crash.
- Есть unit tests с temporary directories на Windows-compatible и POSIX-style сценарии.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B3-02. Ignore rules и классификация файлов

Статус: TODO  
Зависимости: B3-01

Сделать deterministic file indexer без архитектурных выводов.

Критерии приемки:

- Исключаются `.git`, `node_modules`, `dist`, `build`, `target`, `coverage`, archives, images, binaries, generated clients, minified files и oversized files.
- `.gitignore` учитывается без выхода за root.
- Для каждого файла фиксируются relative path, size, language/status, SHA-256 и readable/unreadable state.
- Есть unit tests на ignore precedence, binary detection, max size и encoding failure.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B3-03. Git metadata

Статус: TODO  
Зависимости: B3-01

Получать commit, branch, dirty state и tree hash без выполнения анализируемого кода.

Критерии приемки:

- Git вызывается только ограниченными read-only командами.
- Non-Git mode возможен только при явном config flag.
- Dirty tree не ломает audit, но tree hash обязателен.
- Есть unit/integration tests на git repo fixture, dirty repo и non-Git rejection.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B3-04. Secret redaction

Статус: TODO  
Зависимости: B3-02

Реализовать локальную маскировку secrets перед LLM-контекстом.

Критерии приемки:

- Маскируются private keys, bearer tokens, JWT, passwords, connection strings, client secrets, authorization headers, `.env` content и certificate bodies.
- Оригинальный файл не изменяется.
- Диапазоны строк сохраняются.
- Redaction event фиксируется без исходного значения.
- Есть unit tests на каждый класс секрета и на отсутствие false positive для обычных URL.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B3-05. Analysis unit detection

Статус: TODO  
Зависимости: B3-02, B3-03

Определять analysis units по manifest/deployment/source-root signals.

Критерии приемки:

- Поддержаны `pom.xml`, Gradle, `package.json`, Dockerfile, Helm/deployment manifests, OpenAPI, application config и fallback по директориям.
- Unit содержит root paths, manifests, entry points, config files, relevant source files, candidate name, dependency hints, token estimate и file hashes.
- Нет загрузки всего репозитория в память при больших trees.
- Есть integration test на fixture repositories.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

---

## 6. Epic B4. LLM provider and structured calls

### B4-01. LlmProvider interface и FakeLlmProvider

Статус: TODO  
Зависимости: B1-02

Ввести provider abstraction без зависимости domain layer от GigaChat.

Критерии приемки:

- Interface поддерживает `generate_structured`, `count_tokens`, `list_models`, `health_check`, usage metadata и cancellation.
- Fake provider возвращает те же domain/contract types, что real provider.
- Tests не используют сеть и credentials.
- Есть unit tests на fake responses, cancellation и provider error mapping contract.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B4-02. GigaChatProvider OAuth и health

Статус: TODO  
Зависимости: B4-01, B0-01

Реализовать OAuth/token cache/list models без попадания credentials в логи.

Критерии приемки:

- Access token кэшируется и обновляется до истечения.
- 401 обновляет token один раз, затем fail.
- `verify_ssl_certs=False` недоступен вне явно маркированного local debug.
- Health check проверяет доступность models endpoint.
- Unit tests используют fake HTTP transport.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B4-03. Structured JSON Schema call

Статус: TODO  
Зависимости: B4-02, B1-02

Реализовать strict structured calls для GigaChat.

Критерии приемки:

- System message всегда первый.
- `response_format.type = json_schema`, `strict = true`.
- Invalid JSON/schema делает один repair call; regex fallback запрещен.
- Truncated response и blacklist finish reason не публикуют fact.
- Unit tests покрывают success, invalid JSON, repair success/failure и truncated response.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B4-04. Token budget, retry и bounded concurrency

Статус: TODO  
Зависимости: B4-03

Добавить token counting, retry policy и semaphore.

Критерии приемки:

- Input budget разделен на system, task, source context и output reserve.
- При превышении context уменьшается детерминированно, без произвольного обрезания конца файла.
- Retry policy соответствует таблице раздела 12.6 архитектуры.
- Retries не обходят semaphore.
- Есть unit tests на 400/401/413/422/429/5xx/timeout mappings и concurrency limit.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

---

## 7. Epic B5. Validation pipeline

### B5-01. Schema validator

Статус: TODO  
Зависимости: B1-02, B4-03

Проверять structured output до попадания в candidate store.

Критерии приемки:

- Проверяются JSON validity, Pydantic/schema, required fields, enum values, evidence refs, finish reason и truncation.
- Невалидный повтор после repair получает `FAILED_SCHEMA`.
- Free text не парсится регулярными выражениями.
- Есть unit tests на все failure modes.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B5-02. Evidence integrity validator

Статус: TODO  
Зависимости: B3-02, B1-02

Заново проверять каждый evidence against repository snapshot.

Критерии приемки:

- Проверяется file hash, line range, fragment hash, path containment и excluded file status.
- Source change во время аудита дает `STALE_SOURCE` и warning `REPOSITORY_CHANGED_DURING_AUDIT`.
- Evidence на excluded file отклоняется.
- Есть unit/integration tests на stale hash, wrong line range, fragment mismatch и path escape.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B5-03. Deterministic semantic validator

Статус: TODO  
Зависимости: B1-02, B3-05

Проверять факты без LLM по исходным сигналам.

Критерии приемки:

- Runtime call не создается только на основании build dependency.
- Kafka topic, datasource, URL/client name, OpenAPI operation и deployment name проверяются по evidence.
- Parent type, edge direction, source/target existence и duplicate edge проверяются детерминированно.
- Есть unit tests на confirmed, review-required и rejected cases.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B5-04. Independent LLM validator

Статус: TODO  
Зависимости: B4-04, B5-01, B5-02, B5-03

Добавить второй LLM-проход для фактов, претендующих на confirmed state.

Критерии приемки:

- Validator не получает chain of thought, analyzer confidence и полный analyzer response.
- Validator получает свежие fragments, перечитанные backend.
- Decisions: `SUPPORTED`, `CONTRADICTED`, `INSUFFICIENT_EVIDENCE`, `AMBIGUOUS`, `INVALID_SEMANTICS`.
- Факты, отклоненные hard deterministic rule, не отправляются в LLM.
- Есть tests через FakeLlmProvider на supported, contradicted и insufficient evidence.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B5-05. Graph-level validator

Статус: TODO  
Зависимости: B2-03, B5-03

Проверять graph snapshot целиком перед публикацией.

Критерии приемки:

- Проверяются acyclic containment, one active parent, required hierarchy, orphan nodes, duplicates, impossible edge types и edges на suppressed nodes.
- Массовое исчезновение ранее confirmed объектов блокирует auto-publish и создает review issue.
- Есть unit tests на каждый invariant.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

---

## 8. Epic B6. Audit orchestration and API

### B6-01. Audit state machine

Статус: DONE  
Зависимости: B2-02

Реализовать deterministic audit lifecycle.

Критерии приемки:

- Статусы соответствуют разделу 9.1 архитектуры.
- Невалидные переходы отклоняются с reason code.
- Terminal states неизменяемы.
- Есть unit tests на все разрешенные и запрещенные переходы.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B6-02. In-memory queue, cancellation и checkpoints

Статус: DONE  
Зависимости: B6-01, B2-02

Добавить bounded in-memory audit queue для одного backend process.

Критерии приемки:

- Одновременно не запускается второй audit того же project.
- Queue имеет bounded concurrency, timeout и cancellation flag.
- После backend restart активный audit помечается `INTERRUPTED`.
- Checkpoints создаются после этапов из раздела 9.2 архитектуры.
- Есть integration tests на cancel, interrupted startup и duplicate active audit.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B6-03. Projects API

Статус: DONE  
Зависимости: B2-02, B3-01, B4-02

Реализовать `/api/v1/projects` и preflight validation.

Критерии приемки:

- Поддержаны create/list/get/patch/archive project.
- Preflight проверяет repository path, Git metadata mode, GigaChat config, DB writable и active audit conflict.
- API не возвращает абсолютные пути без необходимости.
- Есть integration tests на success и каждую preflight failure category.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B6-04. Audits API и SSE events

Статус: DONE  
Зависимости: B6-02, B3-05

Реализовать запуск аудита, историю, статус, events, cancel, retry и issues.

Критерии приемки:

- `POST /projects/{project_id}/audits` поддерживает idempotency key.
- `GET /audits/{audit_id}/events` отдает SSE без polling.
- Events и issues paginated.
- Cancel не публикует graph snapshot.
- Retry разрешен только для допустимых partial/failure scopes.
- Есть integration tests на event ordering, idempotency, cancel и retry validation.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B6-05. Graphs API

Статус: DONE  
Зависимости: B2-03, B5-05

Реализовать получение graph snapshot/projection, деталей node/edge и revisions.

Критерии приемки:

- `GET /audits/{audit_id}/graph` возвращает projection для frontend.
- Node/edge details включают evidence и validation record.
- Revision create/override/commit не меняет historical snapshot.
- Source preview доступен только через разрешенный endpoint, если будет реализован.
- Есть contract/integration tests на graph projection, evidence details и immutable snapshot.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

---

## 9. Epic B7. Analysis pipeline

### B7-01. Context builder

Статус: DONE  
Зависимости: B3-05, B4-04

Собирать bounded LLM context из analysis units.

Критерии приемки:

- Context содержит только разрешенные redacted fragments.
- Source code помечен как untrusted data.
- Token budget соблюдается без произвольного обрезания конца файла.
- Prompt manifest version/hash включается в invocation metadata.
- Есть unit tests на ordering, budget trimming и prompt injection guard text.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B7-02. Discovery agent

Статус: DONE  
Зависимости: B7-01, B5-01

Извлекать кандидаты областей и компонентов без финальных edges.

Критерии приемки:

- Agent возвращает только schema-valid candidates.
- Каждый candidate имеет evidence references или unresolved question.
- Discovery не публикует graph.
- Есть tests через FakeLlmProvider на valid output и schema failure.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B7-03. Component analyzer

Статус: DONE  
Зависимости: B7-01, B5-01

Извлекать факты по каждому analysis unit.

Критерии приемки:

- Извлекаются component identity, APIs, consumers, clients, Kafka, topics, DB, external systems, candidate parent и candidate edges.
- UNKNOWN используется вместо догадки.
- Мнение модели о confidence игнорируется для final confidence.
- Есть tests на structured output, missing evidence и unknown classification.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B7-04. Normalization and deduplication

Статус: DONE  
Зависимости: B1-02, B7-02, B7-03

Нормализовать кандидаты до валидации.

Критерии приемки:

- Выполняются trim, Unicode normalization, case-insensitive aliases, service name normalization и stable key generation.
- Exact duplicates объединяются с evidence merge.
- Ambiguous merge не выполняется автоматически и создает DuplicateCandidateIssue.
- Есть unit tests на aliases, artifact/deployment/package matching и ambiguous duplicate.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B7-05. Graph assembler

Статус: DONE  
Зависимости: B5-05, B7-04, B2-03

Собирать snapshot только из validated facts.

Критерии приемки:

- REJECTED facts не включаются.
- UNCONFIRMED отображаются только в debug/review layer.
- Confidence рассчитывается backend policy.
- Snapshot сохраняется одной транзакцией.
- Есть integration test на simple-rest golden graph и ambiguous fixture rejection.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

---

## 10. Epic B8. Manual revisions and incremental audit

### B8-01. Manual overrides

Статус: DONE  
Зависимости: B6-05

Реализовать ручные операции ADD/UPDATE/MOVE/SUPPRESS/RESTORE для nodes и edges.

Критерии приемки:

- Inferred entity suppression не удаляет исходную запись.
- Hierarchy node с детьми и node с edges требуют подтвержденной стратегии.
- AUTOMATED_SYSTEM и FUNCTIONAL_SUBSYSTEM требуют усиленного подтверждения.
- Есть unit/integration tests на все operation types и dangerous deletion cases.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

### B8-02. Incremental audit reuse

Статус: DONE  
Зависимости: B7-05, B8-01

Переиспользовать результаты неизмененных units.

Критерии приемки:

- Reuse разрешен только при совпадении file hashes, dependencies, prompt version, schema version, ontology version и validation policy.
- Новый audit всегда получает самостоятельный snapshot.
- Изменение OpenAPI/topic/deployment/parent invalidates dependent units.
- Есть integration test: изменение одного сервиса не вызывает повторный анализ неизмененных units.

Проверки:

- `python -m pytest`
- `python -m ruff check .`

---

## 11. Epic B9. Fixtures, quality gates and release packaging

### B9-01. Fixture repositories

Статус: DONE  
Зависимости: B3-05

Заполнить artificial fixture repositories.

Критерии приемки:

- `simple-rest` содержит два сервиса и один подтвержденный HTTP-вызов.
- `kafka-services` содержит producer, consumer и topic.
- `ambiguous-architecture` содержит похожие имена, false imports и insufficient evidence.
- Каждый fixture имеет expected golden graph.
- Нет реальных корпоративных исходников и секретов.

Проверки:

- `python -m pytest`
- fixture scan integration tests

### B9-02. OpenAPI snapshot and generated frontend client

Статус: DONE  
Зависимости: B6-05

Синхронизировать backend OpenAPI snapshot и generated TypeScript client.

Критерии приемки:

- OpenAPI генерируется из FastAPI/Pydantic.
- `contracts/openapi.snapshot.json` обновляется автоматической командой.
- Frontend client генерируется, ручные DTO не дублируют backend contracts.
- Contract test падает при drift между backend и snapshot.

Проверки:

- `python -m pytest`
- `npm run typecheck:web`
- `npm run test:web`

### B9-03. Cross-platform bootstrap

Статус: DONE  
Зависимости: B0-01, B2-01

Сделать надежный setup для Windows-дома и Linux-на-работе.

Критерии приемки:

- `scripts/bootstrap.sh` поднимает backend venv и frontend dependencies на Linux.
- README содержит команды для Windows PowerShell и Linux shell.
- Нет обязательной зависимости от глобально установленного formatter/linter кроме Python, Node и npm.
- Есть smoke checklist: install, test, lint, typecheck, build, run API, run web.

Проверки:

- fresh clone/copy smoke на Windows
- fresh copy smoke на Linux

### B9-04. Manual GigaChat smoke test documentation

Статус: DONE  
Зависимости: B4-03

Описать ручную проверку real provider без включения credentials в CI.

Критерии приемки:

- Документ описывает OAuth, list models, token count, structured response, invalid schema behavior, 413 re-chunk, rate limit behavior и token refresh.
- Credentials берутся только из env/local secret store.
- Raw prompts/source fragments не логируются.
- Smoke test можно пропустить в CI без пометки build failure.

Проверки:

- manual run with approved credentials
- automated fake provider tests

---

## 12. Текущий статус

| ID | Название | Статус |
| --- | --- | --- |
| BOOT-01 | Repository bootstrap: структура, docs, health-check apps | DONE |
| B0-01 | Конфигурация backend | DONE |
| B0-02 | Единый формат ошибок и request id | DONE |
| B0-03 | Structured logging | DONE |
| B1-01 | Доменные enum и value objects | DONE |
| B1-02 | Pydantic graph/evidence/validation contracts | DONE |
| B1-03 | Confidence policy | DONE |
| B2-01 | SQLite session и Alembic baseline | DONE |
| B2-02 | Audits и events storage | DONE |
| B2-03 | Graph snapshots и revisions storage | DONE |
| B3-01 | Path safety | DONE |
| B3-02 | Ignore rules и file classification | DONE |
| B3-03 | Git metadata | DONE |
| B3-04 | Secret redaction | DONE |
| B3-05 | Analysis unit detection | DONE |
| B4-01 | LlmProvider и FakeLlmProvider | DONE |
| B4-02 | GigaChat OAuth и health | DONE |
| B4-03 | Strict structured JSON Schema call | DONE |
| B4-04 | Token budget, retry, bounded concurrency | DONE |
| B5-01 | Schema validator | DONE |
| B5-02 | Evidence integrity validator | DONE |
| B5-03 | Deterministic semantic validator | DONE |
| B5-04 | Independent LLM validator | DONE |
| B5-05 | Graph-level validator | DONE |
| B6-01 | Audit state machine | DONE |
| B6-02 | Queue, cancellation, checkpoints | DONE |
| B6-03 | Projects API | DONE |
| B6-04 | Audits API и SSE events | DONE |
| B6-05 | Graphs API | DONE |
| B7-01 | Context builder | DONE |
| B7-02 | Discovery agent | DONE |
| B7-03 | Component analyzer | DONE |
| B7-04 | Normalization and deduplication | DONE |
| B7-05 | Graph assembler | DONE |
| B8-01 | Manual overrides | DONE |
| B8-02 | Incremental audit reuse | DONE |
| B9-01 | Fixture repositories | DONE |
| B9-02 | OpenAPI snapshot and generated client | DONE |
| B9-03 | Cross-platform bootstrap | DONE |
| B9-04 | Manual GigaChat smoke test documentation | DONE |
