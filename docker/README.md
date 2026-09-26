# Docker

The Compose stack runs the ASP.NET API, the nginx-served SPA, a self-built
PostgreSQL 18 (`postgres`) with Apache AGE and pgvector, RabbitMQ, the Celery
worker and Beat, plus a one-shot initializer for Python-owned database tables.
Redis is a disposable cache, not the Celery broker (RabbitMQ) or the source of
truth for ingestion state (PostgreSQL). All Docker-related files are kept in
this folder.

## First run

1. Create the ignored environment file and fill in the database credentials, API
   connection string, signing key, Redis connection string and provider keys:

   ```sh
   cp docker/.env.example docker/.env
   ```

   `PG*` values and `API_PG_CONNECTION_STRING` must point to the same database.
   The Compose `postgres` service reads `PGUSER`/`PGPASSWORD`/`PGDATABASE` for its
   `POSTGRES_*` variables, so there is a single set of credentials to edit.
   Use URI-safe alphanumeric characters for the RabbitMQ password, because it is
   embedded in the AMQP URL used by Celery.
   `REDIS_CONNECTION_STRING` is the complete Redis URI and must be treated as a
   secret even when it contains credentials. The committed example points at
   the local Compose Redis service; use your deployment's secret store for a
   credentialed/TLS endpoint. Python reads the URI through the
   `redis.connection_string_env` reference in `configs/local.yaml`; the API
   receives the same URI through `Redis__ConnectionString`.
   `configs/local.yaml` resolves LLM secrets from the provider environment
   variables; if a configured key is unavailable, either provide it in
   `docker/.env` or edit the model list in that config. Do not put secrets in
   the YAML file or commit `docker/.env`.

2. Start the database, then apply the API's EF migrations to it from the host.
   Migrations are deliberately not run automatically, and the host reaches the
   container's PostgreSQL on `localhost:${POSTGRES_HOST_PORT}` (the containers
   use the service name `postgres`):

   ```sh
   docker compose --env-file docker/.env -f docker/compose.yaml up -d postgres

   set -a
   . docker/.env
   set +a
   ConnectionStrings__PgConnectionString="Host=localhost;Port=${POSTGRES_HOST_PORT:-5432};Database=${PGDATABASE};Username=${PGUSER};Password=${PGPASSWORD}" \
     dotnet ef database update --project src/api/GraphPlatform.Api
   ```

3. Start the rest of the stack from the repository root:

   ```sh
   docker compose --env-file docker/.env -f docker/compose.yaml up --build
   ```

   The `postgres` service creates the `age` and `vector` extensions in
   `POSTGRES_DB` the first time its data directory is initialized. The Python
   initializer also creates the Python-owned tables and per-model embedding
   indexes, and runs once before the worker and Beat. API-owned tables remain
   under EF migration control. Redis has no persistence configured and uses an
   eviction policy because cached values are rebuildable; an outage falls back
   to PostgreSQL reads and best-effort worker invalidation.

## PostgreSQL image

`docker/postgres/Dockerfile` builds `graph-platform/postgres-age-vector:local` in two
stages from the **official** `postgres:18.6-trixie` image. It compiles, from
their official upstream sources:

- **PostgreSQL 18.6** — `docker-library/postgres` (`postgres:18.6-trixie`).
- **Apache AGE 1.8.0 for PG18** — `apache/age`, tag `PG18/v1.8.0-rc0`
  (release tarball pinned and SHA-256 verified).
- **pgvector 0.8.6** — `pgvector/pgvector`, tag `v0.8.6` (pinned and SHA-256
  verified).

The builder stage installs the toolchain (`build-essential`, `flex`, `bison`,
`perl`, `postgresql-server-dev-18`) and stages both extensions with `DESTDIR`;
the runtime stage copies only the compiled libraries and extension SQL. No
third-party combined PostgreSQL/AGE/vector image is used, because none of them
can be trusted to track the official upstream releases and build flags the way
this repository's other images pin their sources.

PostgreSQL 18 changed the official image's data layout: `PGDATA` is now
`/var/lib/postgresql/18/docker` and the declared volume is `/var/lib/postgresql`.
The `postgres` service therefore bind-mounts `data/volumes/postgres` at
`/var/lib/postgresql`, not the pre-18 `/var/lib/postgresql/data`.

Verifying the extensions:

```sh
docker compose --env-file docker/.env -f docker/compose.yaml exec postgres \
  psql -U "$PGUSER" -d "$PGDATABASE" \
  -c "SELECT version();" \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname IN ('age','vector');"
```

Apache AGE is a per-session extension: the application `LOAD`s it and sets
`search_path = ag_catalog, "$user", public` on every connection (see
`common/database/connection.py`), which is the approach the official setup
documentation prescribes. Nothing is applied globally.

## Connecting from the application

Inside Compose, services connect to PostgreSQL at hostname `postgres`, port
`5432`, using `PGUSER`/`PGPASSWORD`/`PGDATABASE` (Python) or
`API_PG_CONNECTION_STRING` (the API's `ConnectionStrings__PgConnectionString`).
From the host, the service is published on `127.0.0.1:${POSTGRES_HOST_PORT}`
(default `5432`) — connect to `localhost` with the same credentials.

## Endpoints

- Frontend: <http://localhost:8080>
- API: <http://localhost:5087>
- RabbitMQ management UI: <http://localhost:15672> (credentials from `docker/.env`)

The browser calls the API directly. The frontend reads its configuration from
`/config.js`, which the container entrypoint renders at startup from the
`FRONTEND_*` environment — changing them needs only a container restart, not a
rebuild (`docker compose ... up -d frontend`). `VITE_APP_NAME` remains a
build-time arg for the static `<title>` fallback. Set `CORS_ALLOWED_ORIGIN` to
the browser-visible frontend origin if it differs from `http://localhost:8080`.

## Redis cache

The API caches model-config and Knowledge Base DTO reads for 30 seconds, and
index-job progress for 2 seconds. API writes evict affected read models; the
ingestion worker evicts job/Knowledge Base entries after committing state
transitions. Membership is always checked in PostgreSQL before serving cached
organization data. Redis errors are non-fatal: API reads fall through to
PostgreSQL, worker invalidation is best-effort, and TTLs bound stale entries.

The API and worker share the versioned `graph-platform:api:v1` key contract in
their respective implementations. IDs are SHA-256 hashed as key components, so
raw tenant/resource IDs do not appear in Redis key names. PostgreSQL remains the
only source of truth for API resources and ingestion job state.

## Images and services

- `docker/postgres/Dockerfile`: official PostgreSQL 18.6 with Apache AGE 1.8.0
  and pgvector 0.8.6 compiled from their official sources.
- `Dockerfile.api`: .NET 10 SDK publish stage and ASP.NET 10 runtime.
- `Dockerfile.ingestion-worker`: Python 3.14 + uv; used by schema-init, worker
  and Beat. `data/volumes/storage` is shared with the API for object storage.
- `redis`: Redis 8.2 LTS, used only for API read-model caching and worker invalidation;
  its port is published on localhost for development.
- `Dockerfile.agent-runtime`: buildable developer smoke-test image, not started
  by Compose because the agent package does not expose an HTTP server.
- `Dockerfile.frontend`: Node build stage and nginx static runtime with SPA
  fallback routing, plus a startup entrypoint that renders `/config.js` from
  `FRONTEND_*`.

The worker and Beat mount `configs/local.yaml` read-only so configuration edits
do not require rebuilding the images. PostgreSQL, RabbitMQ and uploaded files
persist in bind mounts under `data/volumes/` (`postgres/`, `rabbitmq/`,
`storage/`). Beat's schedule is kept in `/tmp` and is recreated with its
container.

Useful commands:

```sh
docker compose --env-file docker/.env -f docker/compose.yaml config
docker compose --env-file docker/.env -f docker/compose.yaml logs -f postgres api ingestion-worker ingestion-beat
docker compose --env-file docker/.env -f docker/compose.yaml down
```
