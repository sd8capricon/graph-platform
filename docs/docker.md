# Docker

All Docker-related files live in `docker/`. The Compose stack runs the ASP.NET API, the nginx-served SPA, RabbitMQ, the Celery worker and Beat, plus a one-shot Python schema initializer. PostgreSQL is external and shared by all services.

## Configuration

### Dockerfiles

Build context for every image is the repository root (`context: ..`).

| Dockerfile                           | Base images                                                                                | Notes                                                                                                                                                                                              |
| ------------------------------------ | ------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docker/Dockerfile.api`              | `mcr.microsoft.com/dotnet/sdk:10.0` build → `mcr.microsoft.com/dotnet/aspnet:10.0` runtime | `dotnet publish --configuration Release --output /app/publish`; `EXPOSE 5087`; `ENTRYPOINT ["dotnet", "GraphPlatform.Api.dll"]`; runs as `app` user                                                |
| `docker/Dockerfile.ingestion-worker` | `python:3.14-slim` + `ghcr.io/astral-sh/uv:0.12.10`                                        | Copies `src/common/`, `src/ingestion-worker/`, `configs/local.yaml`, `docker/init_python_schema.py`; `uv sync --locked --no-dev`; default `CMD celery worker` (overridden per service)             |
| `docker/Dockerfile.agent-runtime`    | `python:3.14-slim` + `ghcr.io/astral-sh/uv:0.12.10`                                        | Copies `src/common/`, `src/agent-runtime/`, `configs/local.yaml`; `CMD ["agent-runtime"]`. Buildable developer smoke-test image, not started by Compose (no HTTP server)                           |
| `docker/Dockerfile.frontend`         | `node:22-alpine` build → `nginx:alpine` runtime                                            | `npm ci` + `npm run build`; `VITE_*` values baked at build time via `ARG`; serves `/usr/share/nginx/html/` with `docker/nginx.conf` SPA fallback (`try_files $uri $uri/ /index.html`); `EXPOSE 80` |

### `.dockerignore`

One file per Dockerfile (`docker/Dockerfile.<name>.dockerignore`). All four are currently identical:

```text
**/.git
**/.venv
**/node_modules
**/bin
**/obj
**/TestResults
**/__pycache__
**/*.pyc
data/storage
src/api/GraphPlatform.Api/appsettings.Development.json
```

### Environment variables

Copy `docker/.env.example` to `docker/.env` (gitignored via `docker/.gitignore`) and fill it in. Do not commit `docker/.env`.

```sh
cp docker/.env.example docker/.env
```

| Variable                                                                                                                                     | Used by                                                    | Notes                                                                                       |
| -------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `PGHOST`, `PGPORT` (default `5432`), `PGDATABASE`, `PGUSER`, `PGPASSWORD`                                                                    | `python-schema-init`, `ingestion-worker`, `ingestion-beat` | External PostgreSQL; must permit creating the `age` and `vector` extensions                 |
| `API_PG_CONNECTION_STRING`                                                                                                                   | `api` (`ConnectionStrings__PgConnectionString`)            | Same database as `PG*` above, Npgsql format                                                 |
| `JWT_SIGNING_KEY`                                                                                                                            | `api` (`Jwt__SigningKey`)                                  | At least 32 characters                                                                      |
| `RABBITMQ_USER` (default `graphplatform`), `RABBITMQ_PASSWORD`                                                                               | `rabbitmq`, `ingestion-worker`, `ingestion-beat`           | URI-safe alphanumeric only; embedded in `RABBITMQ_URL=amqp://<user>:<pass>@rabbitmq:5672//` |
| `CORS_ALLOWED_ORIGIN` (default `http://localhost:8080`)                                                                                      | `api` (`Cors__AllowedOrigins__0`)                          | Browser-visible frontend origin                                                             |
| `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OLLAMA_API_KEY`                                                                     | `python-schema-init`, `ingestion-worker`, `ingestion-beat` | Secrets referenced by `configs/local.yaml`                                                  |
| `VITE_APP_NAME` (default `GraphForge`), `VITE_API_BASE_URL` (default `http://localhost:5087`), `VITE_MAX_UPLOAD_BYTES` (default `104857600`) | `frontend` build `args`                                    | Baked into assets at image-build time; changing them requires `build frontend`              |

Fixed (not overridable via `.env`): `ASPNETCORE_ENVIRONMENT=Production`, `ASPNETCORE_URLS=http://+:5087`, `Storage__Provider=filesystem`, `Storage__FileSystem__Root=/data/storage`, `INGESTION_CONFIG_PATH=/app/configs/local.yaml`.

### Ports

| Host → container           | Service                           |
| -------------------------- | --------------------------------- |
| `5672:5672`, `15672:15672` | `rabbitmq` (AMQP + management UI) |
| `5087:5087`                | `api`                             |
| `8080:80`                  | `frontend`                        |

`python-schema-init`, `ingestion-worker`, `ingestion-beat` publish no ports.

### Volumes

| Volume / mount                                     | Purpose                                                                                  |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `rabbitmq-data:/var/lib/rabbitmq`                  | RabbitMQ persistence (named volume)                                                      |
| `storage-data:/data/storage`                       | Object storage, shared by `api`, `python-schema-init`, `ingestion-worker` (named volume) |
| `../configs/local.yaml:/app/configs/local.yaml:ro` | Worker/Beat/schema-init config; edits need no image rebuild                              |
| Beat `--schedule=/tmp/celerybeat-schedule`         | Ephemeral; recreated with the container                                                  |

### Networks

No custom networks are defined; all services use the Compose default network. The worker and Beat reach RabbitMQ at hostname `rabbitmq:5672`.

## Build

Run from the repository root:

```sh
# Build all images
docker compose --env-file docker/.env -f docker/compose.yaml build

# Rebuild just the frontend (required after any VITE_* change)
docker compose --env-file docker/.env -f docker/compose.yaml build frontend

# Build and start in one step
docker compose --env-file docker/.env -f docker/compose.yaml up --build
```

## Services

| Compose service      | Image                                                                                                 | Purpose                                                                                                                                                          |
| -------------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rabbitmq`           | `rabbitmq:4-management-alpine`                                                                        | Celery broker; management UI on `:15672` with healthcheck (`rabbitmq-diagnostics ping`)                                                                          |
| `api`                | Built from `Dockerfile.api`                                                                           | ASP.NET management API on `:5087`                                                                                                                                |
| `python-schema-init` | Built from `Dockerfile.ingestion-worker`, `command: python /app/docker/init_python_schema.py`         | One-shot initializer (`docker/init_python_schema.py`): creates Python-owned tables (`Base.metadata.create_all`) and per-model embedding indexes; `restart: "no"` |
| `ingestion-worker`   | Same image, `command: celery -A ingestion_worker.celery_app worker`                                   | Executes ingestion jobs from RabbitMQ                                                                                                                            |
| `ingestion-beat`     | Same image, `command: celery -A ingestion_worker.celery_app beat --schedule=/tmp/celerybeat-schedule` | Celery Beat dispatcher (claims queued jobs, publishes tasks)                                                                                                     |
| `frontend`           | Built from `Dockerfile.frontend`                                                                      | nginx-served SPA on `:8080`; calls the API directly at `VITE_API_BASE_URL`                                                                                       |

`agent-runtime` has a Dockerfile but no Compose service.

## Compose

Key points in `docker/compose.yaml` (`name: graph-platform`):

- `ingestion-worker` and `ingestion-beat` wait for `rabbitmq: service_healthy` and `python-schema-init: service_completed_successfully` via `depends_on`.
- `frontend` has a plain `depends_on: [api]` (start order only).
- `restart: unless-stopped` on everything except `python-schema-init` (`restart: "no"`).
- Worker and Beat mount `configs/local.yaml` read-only, so config edits apply on container restart without a rebuild.
- EF migrations are never run by Compose. Apply them from the host before starting:

```sh
set -a; . docker/.env; set +a
ConnectionStrings__PgConnectionString="$API_PG_CONNECTION_STRING" \
  dotnet ef database update --project src/api/GraphPlatform.Api
```

Validate the resolved config without starting anything:

```sh
docker compose --env-file docker/.env -f docker/compose.yaml config
```

## How to Run

Prerequisites: Docker with Compose, an external PostgreSQL supporting Apache AGE and pgvector, .NET 10 SDK (for the one-time migration), and a filled-in `docker/.env`.

```sh
# 1. Configure
cp docker/.env.example docker/.env
# edit docker/.env: PG*, API_PG_CONNECTION_STRING (same DB), JWT_SIGNING_KEY, RabbitMQ, provider keys

# 2. Apply API migrations (host, once per migration)
set -a; . docker/.env; set +a
ConnectionStrings__PgConnectionString="$API_PG_CONNECTION_STRING" \
  dotnet ef database update --project src/api/GraphPlatform.Api

# 3. Build and start (foreground)
docker compose --env-file docker/.env -f docker/compose.yaml up --build

# 4. Or start detached
docker compose --env-file docker/.env -f docker/compose.yaml up --build -d

# Stop (keeps volumes)
docker compose --env-file docker/.env -f docker/compose.yaml down

# Restart one service
docker compose --env-file docker/.env -f docker/compose.yaml restart ingestion-worker

# Follow logs
docker compose --env-file docker/.env -f docker/compose.yaml logs -f api ingestion-worker ingestion-beat
```

Endpoints: frontend <http://localhost:8080>, API <http://localhost:5087>, RabbitMQ UI <http://localhost:15672>.

## Common Commands

| Task                             | Command                                                                                    |
| -------------------------------- | ------------------------------------------------------------------------------------------ |
| Validate resolved Compose config | `docker compose --env-file docker/.env -f docker/compose.yaml config`                      |
| Build all images                 | `docker compose --env-file docker/.env -f docker/compose.yaml build`                       |
| Start (foreground)               | `docker compose --env-file docker/.env -f docker/compose.yaml up --build`                  |
| Start (detached)                 | `docker compose --env-file docker/.env -f docker/compose.yaml up --build -d`               |
| List services                    | `docker compose --env-file docker/.env -f docker/compose.yaml ps`                          |
| Follow logs (all / one service)  | `docker compose --env-file docker/.env -f docker/compose.yaml logs -f` / `... logs -f api` |
| Restart a service                | `docker compose --env-file docker/.env -f docker/compose.yaml restart ingestion-worker`    |
| Stop (keep volumes)              | `docker compose --env-file docker/.env -f docker/compose.yaml down`                        |
