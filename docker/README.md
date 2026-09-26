# Docker

The Compose stack runs the ASP.NET API, the nginx-served SPA, RabbitMQ, the
Celery worker and Beat, plus a one-shot initializer for Python-owned database
tables. PostgreSQL remains external: use a PostgreSQL instance that supports
both Apache AGE and pgvector. All Docker-related files are kept in this folder.

## First run

1. Create the ignored environment file and fill in the external database
   credentials, API connection string, signing key and provider keys:

   ```sh
   cp docker/.env.example docker/.env
   ```

   `PG*` values and `API_PG_CONNECTION_STRING` must point to the same database.
   Use URI-safe alphanumeric characters for the RabbitMQ password, because it is
   embedded in the AMQP URL used by Celery.
   `configs/local.yaml` resolves LLM secrets from the provider environment
   variables; if a configured key is unavailable, either provide it in
   `docker/.env` or edit the model list in that config. Do not put secrets in
   the YAML file or commit `docker/.env`.

2. Apply the API's EF migrations to the external database from the host before
   starting Compose. Migrations are deliberately not run automatically:

   ```sh
   set -a
   . docker/.env
   set +a
   ConnectionStrings__PgConnectionString="$API_PG_CONNECTION_STRING" \
     dotnet ef database update --project src/api/GraphPlatform.Api
   ```

3. Start the stack from the repository root:

   ```sh
   docker compose --env-file docker/.env -f docker/compose.yaml up --build
   ```

   The external database must permit the Python initializer to create the `age`
   and `vector` extensions, as well as the Python-owned tables and indexes. The
   schema initializer runs once before the worker and Beat. API-owned tables
   remain under EF migration control.

## Endpoints

- Frontend: <http://localhost:8080>
- API: <http://localhost:5087>
- RabbitMQ management UI: <http://localhost:15672> (credentials from `docker/.env`)

The browser calls the API directly. `VITE_API_BASE_URL` is compiled into the
frontend assets at image-build time; changing it requires rebuilding the
frontend (`docker compose ... build frontend`). Set `CORS_ALLOWED_ORIGIN` to
the browser-visible frontend origin if it differs from `http://localhost:8080`.

## Images and services

- `Dockerfile.api`: .NET 10 SDK publish stage and ASP.NET 10 runtime.
- `Dockerfile.ingestion-worker`: Python 3.14 + uv; used by schema-init, worker
  and Beat. `storage-data` is shared with the API for object storage.
- `Dockerfile.agent-runtime`: buildable developer smoke-test image, not started
  by Compose because the agent package does not expose an HTTP server.
- `Dockerfile.frontend`: Node build stage and nginx static runtime with SPA
  fallback routing.

The worker and Beat mount `configs/local.yaml` read-only so configuration edits
do not require rebuilding the images. RabbitMQ data and uploaded files persist
in named volumes. Beat's schedule is kept in `/tmp` and is recreated with its
container.

Useful commands:

```sh
docker compose --env-file docker/.env -f docker/compose.yaml config
docker compose --env-file docker/.env -f docker/compose.yaml logs -f api ingestion-worker ingestion-beat
docker compose --env-file docker/.env -f docker/compose.yaml down
```
