# Knowledge Base publishing → ingestion queue (ADR-0005, stub consumers)

## Context
`POST .../knowledge-bases/{id}/publish` only flips `State` to `indexing`; nothing reaches the worker.
The worker already has the Celery app + RabbitMQ topology (`celery_app.py`), a Beat dispatcher
(`dispatcher.py`) and `IndexJobStore` (`job_store.py`), but the `index_job`/`index_file` tables have
**no EF mapping or migration** (Python docstrings say the API owns their DDL), and the only task
(`ingest_knowledge_base`) always fails non-retryably. Goal: publish writes a durable job (outbox),
the dispatcher enqueues it, and four **stub** stage consumers walk the full ADR DAG
(ontology → per-file entity fan-out → guarded fan-in graph → embedding) doing no real work, ending
with job `completed` and KB `published`.

Decisions (confirmed): outbox + existing dispatcher (API has no RabbitMQ dependency); stubs walk the
whole DAG; one Apache Age graph per organization.

## API (`src/api/GraphPlatform.Api`)
1. **Entities** `Models/IndexJob.cs`, `Models/IndexFile.cs` + enums `IndexJobStatus`
   (Queued, Running, Completed, PartiallyFailed, Failed, Cancelled) and `IndexFileStatus`
   (Pending, Extracting, Extracted, Failed, Skipped). Fields mirror
   `ingestion_worker/models/index_job.py` / `index_file.py` exactly.
2. **`AppDbContext`**: tables `index_job`/`index_file`; **explicit `HasColumnName` snake_case on every
   column** (first mapping to need it — Python models are snake_case, unlike the PascalCase API tables);
   statuses via `Converters.SnakeCaseEnum<T>()`; `index_file.index_job_id` FK cascade; `index_job`
   FK → `knowledge_base.Id` cascade (so org/KB delete cleans up); indexes on `organization_id`,
   `knowledge_base_id`; **partial unique index** on `knowledge_base_id` filtered
   `status IN ('queued','running')` (one active job per KB, closes the double-publish race; raw filter
   SQL works on both Npgsql and SQLite). `created_at` default `now()`/`CURRENT_TIMESTAMP` — set
   explicitly from C# instead to stay provider-neutral.
3. **Migration** `AddIndexJobs` (`dotnet ef migrations add AddIndexJobs --project GraphPlatform.Api`).
4. **`KnowledgeBaseState.Failed`** (ADR "add Failed"). A KB is *editable* when `Draft` or `Failed`:
   replace the draft-only checks in `KnowledgeBasesController` (update/delete/publish) and
   `KnowledgeBaseFilesController` (upload/delete) with one helper (e.g. `KnowledgeBase.IsEditable`).
5. **Graph name**: `Services/GraphNames.cs` → `ForOrganization(orgId)`: `"org_" +` lowercase id with
   non-`[a-z0-9_]` → `_`; if the result exceeds 63 chars (Postgres identifier limit), use
   `"org_" + first 32 hex chars of SHA-256(orgId)`. Only the API computes it; the worker reads
   `index_job.graph_name`.
6. **`PublishKnowledgeBase`** (one `SaveChangesAsync` = one transaction):
   - existing auth/404/403; 409 unless editable; **409 when the KB has no files** (fan-in needs ≥1).
   - `State = Indexing`; insert `IndexJob { Id = Guid, Status = Queued, GraphName, TotalFiles = files.Count,
     EmbeddingModelId = organization.ActiveEmbeddingModelId, RequestedBy = UserId, CreatedAt = now }`
     and one `IndexFile { Status = Pending, FileId = file.Id }` per KB file. Creating file rows here
     (not in the worker) fixes `total_files` before any fan-out, so fan-in can't fire early.
   - `DbUpdateException` from the unique index → 409.
   - Return **202 Accepted** with `KnowledgeBaseDto`, `Location` → the job endpoint.
   - Update class/summary remarks ("worker dispatch ... not wired yet").
7. **Job status read**: `GET .../knowledge-bases/{kbId}/index-jobs/{jobId}` (any member; 404 across
   orgs) returning `IndexJobDto` (status, counters, error, timestamps, files with status/attempts/error).
   Hand-mapped in `Dtos/DtoMappings.cs`; DTO under `Dtos/KnowledgeBases/`.

## Worker (`src/ingestion-worker/src/ingestion_worker`)
1. **`job_store.py`** additions:
   - `list_files(job_id)`; `complete_file(file_row_id) -> bool` — guarded
     `status IN (pending, extracting) → extracted`, returns whether *this* call transitioned.
   - Split `increment_and_check_fan_in` into `record_file_done(job_id)` (counter +1) and
     `claim_graph_dispatch(job_id) -> bool` (existing guarded flip). The entity stage increments **only
     when `complete_file` returned True**, so a redelivery can't double-count; it always retries the claim.
   - Guard `mark_job_completed` on `status == running` (return bool).
   - KB state constants `KB_PUBLISHED = "published"`, `KB_FAILED = "failed"`.
2. **New `stages.py`** (Celery-free, testable like `dispatch_queued_jobs`; each takes
   `session` and an injected `publish(task_name, args)` callable, commits before publishing — same
   convention and documented reconciler gap as the dispatcher). Each skips a missing job or one not
   `running`.
   - `extract_ontology(job_id)`: stub; publish `extract_entities(job_id, file_row_id)` for each file row
     not yet terminal.
   - `extract_entities(job_id, file_row_id)`: stub; `complete_file` → `record_file_done` if
     transitioned → `claim_graph_dispatch`; if claimed, commit then publish `construct_graph(job_id)`.
   - `construct_graph(job_id)`: stub; publish `embed_nodes(job_id, "0")` (single stub batch).
   - `embed_nodes(job_id, batch_id)`: stub; guarded `mark_job_completed` + `set_knowledge_base_state(published)`
     in one commit.
   - Each stub logs `job_id`/`file_row_id` with a `# TODO(ADR-0005 Phase 2)` marker where real work goes.
3. **`tasks.py`**: replace `ingest_knowledge_base` with four tasks
   `ingestion_worker.tasks.{extract_ontology,extract_entities,construct_graph,embed_nodes}`, all on
   `IngestionTask` (same `autoretry_for`/backoff); each is `load_worker_config()` +
   `asyncio.run(run_stage(...))`. `_publish` helper = `app.send_task(name, args=args)`.
   `IngestionTask.on_failure` keeps using `args[0]` as job id.
4. **`jobs.py`**: remove `ingest_job` (the always-failing Phase 1 path); `fail_job` also sets KB state
   `failed` in the same commit; add `run_stage(fn, *args)` opening `open_job_resources()`.
5. **`celery_app.py`**: `task_routes` for each stage task → `q.<stage>` / `ingestion.<stage>`; update
   the module docstring (no longer "Phase 1 single task").
6. **`dispatcher.py`**: `_publish` sends `extract_ontology` instead of `ingest_knowledge_base`.
7. **Launching**: `.vscode/tasks.json` — worker command gets
   `-Q q.ontology,q.entity,q.graph,q.embedding` (without it Celery also consumes the `.retry`/`.dlq`
   queues, defeating the TTL delay and draining the DLQ); add an "Ingestion Worker: celery beat" task
   and include it in "Start All". Add a minimal root `compose.yaml` with `rabbitmq:4-management`
   (5672/15672) since no broker setup exists anywhere.

## Frontend (`src/frontend`)
- `src/api/types.ts`: add `failed` to `KnowledgeBaseState`; status badge label/icon for it.
- `src/org/permissions.ts` / KB detail page: draft-only gating → editable (`draft | failed`); Publish
  disabled-with-reason when the KB has no files (mirrors the new 409).
- Publish mutation: confirm `http.ts` treats 202-with-body like 200 (adjust if it only parses 200).
  Existing polling while `indexing` picks up `published`/`failed` without changes.

## Docs
- `CLAUDE.md` **and its sync counterpart** (same commit): ingestion pipeline section (stage tasks,
  API-created file rows, graph-per-org naming, `Failed` state, `-Q` gotcha, beat), API files/shared-DB
  sections (`index_job`/`index_file` now EF-owned with snake_case columns), Running section.
- ADR-0005: Status → partially implemented; Open Question 1 update (`index_file.file_id` = `file.Id`).

## Verification
- `dotnet test src/api/GraphPlatform.slnx` — new tests in `KnowledgeBaseEndpointTests`: publish → 202,
  job + one pending file row per file, `graph_name`, `requested_by`, `embedding_model_id`; 409 with no
  files; 409 on second publish; republish/edit allowed from `failed`; job GET 404 cross-org.
  `GraphNames` unit tests (sanitising, long-id hash).
- `uv run --project src/ingestion-worker pytest src/ingestion-worker/tests` — new `test_stages.py`
  (SQLite + recording `publish`): 2-file job walks the DAG → `construct_graph` published exactly once,
  job `completed`, KB `published`; redelivered `extract_entities` doesn't double-count or re-publish;
  non-running job is skipped; `fail_job` sets KB `failed`. Update `test_dispatcher.py`,
  `test_celery_app.py` (routes per stage), `test_job_store.py`, delete obsolete `test_jobs.py` case.
- `npm run lint && npx tsc -b` in `src/frontend`.
- End to end: `docker compose up rabbitmq`, apply migration
  (`dotnet ef database update --project GraphPlatform.Api`), run API + worker + beat, upload a file,
  publish → watch queues in the RabbitMQ UI (:15672), KB turns `published`, job GET shows `completed`.
