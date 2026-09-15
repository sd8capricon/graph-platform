# 4. Repository decomposition: four services, staged through one `common` uv project

## Status

Proposed, step 1 implemented. Step 1 — collapse the existing code into a single `common` uv project at
`src/common`, with the import package renamed `graphrag_apacheage` -> `common` — is done; see
"Amendment: step 1 implemented" below, and "Amendment: standalone projects, standard uv layout" for
the later change that dropped the workspace root and moved `common` onto uv's default src layout.
Steps 2+ (extracting `api`, `agent-execution`, and `ingestion` as separate services) are deferred and
deliberately unspecified in mechanism: one `common` package still holds every service's code, exactly
as Decision 3 intended. `ingestion` exists as a scaffolded, empty uv project.

## Context

Today the repository is a single uv project with a single import package:

- Root `pyproject.toml` — `name = "graphrag-apacheage"`, `[project.scripts] graphrag-apacheage =
  "graphrag_apacheage:main"`, `uv_build`, 11 runtime dependencies, a `dev` dependency group
  (`aiosqlite`, `pytest`, `pytest-asyncio`), and `[tool.pytest.ini_options] asyncio_mode = "auto"`.
- One import package at `src/graphrag_apacheage/` — 24 modules, roughly 927 lines of core code —
  split into `agent/`, `database/`, `models/`, `repositories/`, `schemas/`, `services/`, plus
  `config.py` and `__init__.py`.
- `src/graphrag_apacheage/api/app.py` is empty (0 bytes), and `api/routers/` and `api/dependencies/`
  are empty directories with no `__init__.py`. An API layer was anticipated and never built.

Nothing in that layout separates the three workloads the project actually has:

1. **Ingestion** — reading a knowledge base and writing it to Apache Age plus both embedding
   side-tables. `services/knowledge_base_service.py` orchestrates those writes; the demo path
   (`KnowledgeBase.from_json_file()` plus `upsert_knowledge_base()`) lives in `__init__.py`'s
   `create_knowledge_base()`.
2. **Agent execution** — building and running agents, with tools that read the graph and the
   side-tables. `agent/tools.py` imports the ORM models directly (`get_properties_by_name` from
   `models/graph_schema_registry.py`, `vector_search` from `models/node_embedding.py`), so the agent
   package already reaches into persistence.
3. **Management API** — CRUD for graphs, knowledge bases and `Model` configs, agent invocation, and
   ingestion triggering. Currently only empty placeholders plus the demo `main()`/`run()` in
   `__init__.py`, which both ingests a knowledge base and smoke-tests an agent.

Those workloads have different dependency, scaling, and security profiles: ingestion performs bulk
database writes, agent execution needs LLM credentials and runs model-chosen tool calls, and the
management API serves CRUD and triggers the other two. Shipping all three from one import package
forces one dependency set, one process and one deploy unit on all of them.

There is also a decision already on the books that this layout constrains: ADR
[0002](0002-organization-roles-privileges-and-embedding-model-governance.md) leaves the API/build
framework open (.NET vs Python) and notes its decisions are meant to be framework-agnostic. A service
boundary is what makes that framework choice local to `api` instead of repo-wide.

## Decision

### 1. The target topology is four services

| Service | Owns | Today's code that lands there | Depends on |
|---|---|---|---|
| **common** | Shared library: configuration, domain schemas, ORM models, repositories, embedding service, index DDL | `config.py`, `schemas/`, `models/` (incl. `models/base.py`), `repositories/`, `services/embedding_service.py`, `database/indexes.py` | nothing |
| **api** | Management API: CRUD for knowledge bases/graphs/`Model` configs, invoking the agent, triggering ingestion | `api/` placeholders; the orchestration now in `__init__.py`'s demo `main()` | `common` |
| **agent-execution** | Agent runtime: tools, memory, skills, prompt assembly | `agent/tools.py`, `prompts.py`, `deep_agent.py`, `react_agent.py`, `context.py`, `models.py`, `serializers.py`; future memory/skills | `common` |
| **ingestion** | Data ingestion: source reading, knowledge base -> graph + embeddings | `KnowledgeBase.from_json_file()` call path and `KnowledgeBaseService.upsert_knowledge_base()` invocation (today the demo `create_knowledge_base()`) | `common` |

`agent/chat_model.py` stays with `agent-execution` for now. Its convention-consistent home is a
shared service mirroring `EmbeddingService`, and the existing rule in `CLAUDE.md`/`AGENTS.md` is to
move it as soon as a non-agent caller appears — restated here so this split does not pre-empt that.

### 2. Dependencies point one way

Services depend on `common`. `common` depends on no service. Services do not import each other.
Cross-service needs — `api` running an agent, `api` triggering an ingestion job — go through a
defined interface rather than an import. The exact mechanism is an Open Question below; the direction
is not.

### 3. Step 1: one uv workspace, one `common` project at `src/common`

> **Historical as written, then amended twice.** The bullets in this section describe how step 1 was
> first implemented — a workspace root plus a non-standard flat module root. Both were later changed:
> see "Amendment: step 1 implemented" and "Amendment: standalone projects, standard uv layout" at the
> end of this ADR. Read this section as the original decision, not as the current layout.

The near-term shape, which is what this ADR decides and what the next change implements:

```
pyproject.toml                 # workspace root: [tool.uv.workspace] members = ["src/common"]
uv.lock                        # single workspace lockfile
configs/                       # stays at the repo root
dummy_data/                    # stays at the repo root
tests/                         # stays at the repo root, workspace-level
src/
└── common/
    ├── pyproject.toml         # project "graphrag-common"
    └── common/                # import package "common"
        ├── __init__.py
        ├── config.py
        ├── agent/
        ├── database/
        ├── models/
        ├── repositories/
        ├── schemas/
        └── services/
```

- **Root `pyproject.toml` becomes a non-packaged workspace root.** It keeps `[project]` metadata,
  `[dependency-groups] dev`, and `[tool.pytest.ini_options]`; it gains
  `[tool.uv.workspace] members = ["src/common"]`, `dependencies = ["common"]`, and
  `[tool.uv.sources] common = { workspace = true }`; it drops `[build-system]` and
  `[project.scripts]`. Without a build system uv does not build or install the root project itself,
  which is intended: the root is a workspace root, not a package. Dev dependencies stay on the root
  because `uv sync` and `uv run` operate on the workspace root by default, whereas a member's dev
  group needs `--package`/`--all-packages`.
- **`src/common/pyproject.toml`** declares project name `graphrag-common`,
  `requires-python = ">=3.14"`, the 11 runtime dependencies moved verbatim from the root,
  `[build-system]` with `uv_build`, `[project.scripts] graphrag-apacheage = "common:main"`, and
  `[tool.uv.build-backend] module-name = "common"` with `module-root = ""`. The flat module root is
  needed because uv's default is `src` relative to the project directory, which would place the
  package at `src/common/src/common/`.
- **The code moves with `git mv src/graphrag_apacheage src/common/common`** and keeps its existing
  sub-layout (`common/agent/`, `common/models/`, ...) unchanged. Step 1 does **not** reorganize
  modules into service directories, so the later split stays mechanical.
- **Imports are rewritten** `graphrag_apacheage` -> `common` in 46 source import lines and in the 20
  test files under `tests/`. Tests remain at the repo root, workspace-level, not per member.
- **Paths stay CWD-relative.** `configs/` and `dummy_data/` stay at the repo root, and
  `config.py`'s `DEFAULT_CONFIG_PATH = Path("configs/local.yaml")` plus the demo's
  `"dummy_data/f1_kb.json"` keep resolving against the working directory. The move must not make them
  package-relative.
- **Import-cycle rules survive the rename unchanged.** `models/__init__.py`, `services/__init__.py`
  and `repositories/__init__.py` stay docstring-only with no re-exports; `schemas/`, `agent/`,
  `api/` and `database/` continue to have no `__init__.py`; imports stay leaf-module (`from
  common.services.embedding_service import EmbeddingService`).
- `uv lock` regenerates one workspace lockfile. `.venv` is gitignored, so nothing there is tracked.

### 4. `common` is not a dumping ground

A module belongs in `common` only when at least two services need it, or when it is a shared domain
model or the database schema itself. Code used by exactly one service stays in that service even
while it physically sits in the `common` project during the transition. Without this rule the target
topology in Decision 1 never arrives: the default outcome of "move everything into `common` first" is
that `common` becomes the application.

### 5. Module-to-service mapping for the later split (not performed by step 1)

| Module (after step 1's rename) | Target service |
|---|---|
| `common/config.py` | `common` |
| `common/schemas/knowledge_base.py`, `common/schemas/model.py` | `common` |
| `common/models/base.py`, `graph_schema_registry.py`, `node_embedding.py`, `schema_embedding.py` | `common` |
| `common/repositories/age_graph_repository.py` | `common` |
| `common/services/embedding_service.py` | `common` |
| `common/services/knowledge_base_service.py` | `common` (shared orchestration; called by `ingestion`) |
| `common/database/indexes.py` | `common` |
| `common/agent/tools.py`, `prompts.py`, `deep_agent.py`, `react_agent.py`, `serializers.py` | `agent-execution` |
| `common/agent/context.py` | `agent-execution` (see the `AgentContext` Open Question) |
| `common/agent/models.py` (`NodeRef`) | `agent-execution` |
| `common/agent/chat_model.py` | `agent-execution` until a non-agent caller appears (Decision 1) |
| `common/api/**`, demo `main()`/`run()` | `api` / `ingestion`, per the Open Questions |

## Consequences

- **Step 1 is a pure relocation.** Its whole cost is the source and test import lines plus every
  `src/graphrag_apacheage/...` path string in `CLAUDE.md`/`AGENTS.md` (25 occurrences in each). Those
  two instruction files are updated in the same commit as the move, because they are required to stay
  identical to one another and to describe the present layout.
- **The root project is no longer installable or buildable.** `uv build` at the root builds nothing;
  `uv run` still works from the root because the root depends on the `common` member. Runnables
  (`[project.scripts]`) necessarily live on a packaged member, i.e. on `src/common/pyproject.toml`.
- **No runtime behavior change is expected.** Acceptance for step 1: `uv run pytest` is green with
  test bodies unchanged except import lines; `uv run python -c "from common.agent.tools import
  GRAPH_TOOLS"` succeeds in a fresh interpreter (the import-cycle sanity check the codebase already
  prescribes); `uv run graphrag-apacheage` still starts (it needs Postgres and `.env`).
- **`requires-python` stays `>=3.14`.** uv enforces one intersection across the workspace.
- **The boundary is a review rule, not a tool-enforced one.** uv cannot ensure a package uses only
  its declared dependencies, and in step 1 there is only one real package anyway. Enforcement starts
  mattering in step 2.

## Open Questions

- **Inter-service interface.** HTTP/REST vs gRPC vs staying in-process. `AgentContext` currently
  carries a live `AsyncSession` and `AgeGraphRepository`, which are process-local objects and cannot
  cross a network boundary. Either `agent-execution` constructs its own connection per run from
  scalar ids (the recommended direction, since ADR-0002 already scopes every run by
  `organization_id` + `graph_name`), or step 2 keeps the services in one process.
- **Whether `common` splits further** (for example contracts vs. database layer) — deferred until a
  service actually needs a narrower dependency set.
- **Packaging and deployment.** One image per service vs. one image with several entrypoints. There
  is no CI yet (`.github/` does not exist), so nothing pins this decision today.
- **API framework.** Still undecided per ADR-0002; this ADR only makes the choice local to `api`.
- **Whether `ingestion` is a library called by `api` or an independently deployed worker.** That
  depends on ADR-0002 Decision 4's recalculation job, which does not exist yet either.
- **What the demo `main()`/`run()` in `__init__.py` becomes** — an ingestion entrypoint, an api
  startup hook, or a dev-only script. It currently does both ingestion and an agent smoke test, so it
  has no single owner under the target topology.

## Amendment: step 1 implemented

Decision 3 is implemented, with these concrete details settled during it:

- Root `pyproject.toml` keeps `[project]` (name `graphrag-apacheage`, version `0.1.0`) but has no
  `[build-system]`, so uv does not build or install the root; its `dependencies` is just
  `["graphrag-common"]` with `[tool.uv.sources] graphrag-common = { workspace = true }`, and it keeps
  `[dependency-groups] dev` (`aiosqlite`, `pytest`, `pytest-asyncio`) and
  `[tool.pytest.ini_options]`.
- `src/common/pyproject.toml` declares project name `graphrag-common` (not `common`), so the
  distribution name stays unambiguous while the import package is the short `common`. It carries the
  11 runtime dependencies verbatim, `requires-python = ">=3.14"`, the `uv_build` build system, the
  `graphrag-apacheage = "common:main"` script, and
  `[tool.uv.build-backend] module-name = "common"` with `module-root = ""` so the package sits at
  `src/common/common/`.
- The member declares no `readme`; the (empty) `README.md` stays at the repository root, where the
  workspace root's metadata points.
- Package modules moved with `git mv` (history preserved) and keep their sub-layout. Imports were
  rewritten `graphrag_apacheage` -> `common` in 24 source modules and 20 test files. `configs/` and
  `dummy_data/` were not touched, so `DEFAULT_CONFIG_PATH` and the demo JSON path stay
  working-directory-relative.
- Verification: `uv lock` resolves one workspace lockfile containing `graphrag-common`; `uv sync`
  replaces the old root package with the member; `uv run pytest tests/` passes 151 tests; and a fresh
  interpreter can `from common.agent.tools import GRAPH_TOOLS` (the codebase's prescribed
  import-cycle check).
- `CLAUDE.md` and `AGENTS.md` carry the new paths and an updated `### Key Files` block in the same
  change, identically.

## Amendment: standalone projects, standard uv layout

Two later changes removed the workspace root and the non-standard module root this ADR originally
specified. They are recorded here because both are visible in the repository layout, and because the
second one is what the ADR should have said from the start.

**The workspace root is gone.** The root `pyproject.toml` and root `uv.lock` were deleted, and the
member project was renamed `graphrag-common` -> `common`. Each service is now a standalone uv project
with its own `pyproject.toml`, `.venv` and `uv.lock`:

```
configs/                       # repository root
dummy_data/
tests/                         # run against the common project environment
src/
├── common/                    # uv project "common"
│   ├── pyproject.toml
│   ├── uv.lock
│   └── src/
│       └── common/            # import package "common"
└── ingestion/                 # uv project "ingestion" (scaffolded by `uv init`)
    ├── pyproject.toml
    ├── README.md
    ├── .python-version
    └── src/
        └── ingestion/
```

Consequences of dropping the workspace: there is no single lockfile, so dependency versions are no
longer resolved jointly across services (acceptable while `ingestion` has no dependencies of its own,
but it is the tradeoff to watch as services start sharing pins); and `uv run` no longer works from the
repository root, because no `pyproject.toml` is there to identify a project.

**The module root is now uv's default.** `[tool.uv.build-backend]` is gone from
`src/common/pyproject.toml` entirely. The `module-root = ""` override existed only to avoid
`src/common/src/common/`; that path is in fact uv's standard src layout, and this project now uses it
deliberately. Because the project is named `common`, uv's name-normalization rule already derives the
module name `common`, so not even `module-name` needs to be stated.

Two things the deletion of the root project took with it, and how they are handled now:

- **pytest configuration.** `asyncio_mode = "auto"` lived in the root `[tool.pytest.ini_options]`.
  With no root project, the root-level suite is run against the `common` environment with the setting
  passed on the command line:
  ```bash
  uv run --project src/common --with pytest --with pytest-asyncio --with aiosqlite \
    pytest tests/ -o asyncio_mode=auto
  ```
  151 tests pass this way. If the root-level `tests/` directory is meant to stay outside every
  service project permanently, moving the dev group and this pytest config into a project that owns
  the suite is the follow-up to make the command plain `uv run pytest` again.
- **One editable install path.** `common` is installed into `src/common/.venv`, so a root-level
  `tests/` run needs `--project src/common`; there is no longer a repository-root environment that
  imports `common` implicitly.

