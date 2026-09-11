# Agent Customization for graphrag-apacheage

> **Sync note:** This file and `CLAUDE.md` must stay identical. Edit one, copy change to other, same commit.
> **Keep current:** When you learn new patterns, conventions, or gotchas during work, add them to both files, same commit. Don't let docs drift from code.

## Project Overview

**graphrag-apacheage** is a Python library that bridges Microsoft's GraphRAG framework with Apache Age, a graph database extension for PostgreSQL. It provides data models, schema registry, and utilities for managing knowledge graphs in a relational database with graph capabilities.

**Stage**: Early development (0.1.0)  
**Python**: 3.14+ required  
**Build System**: uv (ultra-fast Python package installer)

## Architecture

### Core Components

1. **Schemas** (`src/graphrag_apacheage/schemas/`)
   - `KnowledgeBase`: Container for nodes and relationships with JSON serialization
   - `KnowledgeNode`: Graph node with unique ID, label, and properties
   - `KnowledgeRelationship`: Graph edge connecting nodes with label and properties
   - Schema extraction to `GraphSchemaRegistry` for database storage
   - `Model` (`schemas/model.py`): Configured LLM/embedding provider connection (display_name, name,
     provider, connection_string, auth_mode, type capabilities, api_key, embedding_dimension) —
     validates that `api_key` is set when `auth_mode` is `api_key` and `embedding_dimension`
     is set when `embedding` is in `type`. Passed into `EmbeddingService.compute_embeddings()`
     to describe which provider/model to call.
   - Config entries name a secret indirectly via `api_key_env`; a `@model_validator(mode="before")`
     (`resolve_api_key_env`) pops it and reads that environment variable into `api_key`, so raw YAML
     entries validate straight into `Model`. There is no `Model.from_config()` — `AppSettings`
     (`config.py`) owns file reading, and the config file is parsed exactly once.

2. **Models** (`src/graphrag_apacheage/models/`)
   - `Base` (`models/base.py`): shared SQLAlchemy `DeclarativeBase` for all ORM models
   - `GraphSchemaRegistry`: SQLAlchemy ORM model tracking node/relationship type definitions
   - Stores: graph name, knowledge base IDs (list; a label may come from multiple knowledge bases), entity type, name, description, aliases, properties, source/target labels
   - Core method: `upsert_records()` - merges new schemas with existing definitions
   - `NodeEmbedding`: SQLAlchemy ORM model storing one vector embedding per knowledge base node
   - Stores: graph name, knowledge base ID, node ID, label, properties snapshot, embedding vector
   - Core methods: `upsert_records()` - inserts/updates node embeddings; `vector_search()` - cosine-similarity search
   - Both models share the pgvector embedding column pattern and delegate embedding computation
     to `EmbeddingService`; see "Vector Embedding & Search Pattern" below

3. **Agents** (`src/graphrag_apacheage/agent/`)
   - `context.py` - `AgentContext`: pydantic model passed as `context_schema` to LangChain's
     `create_agent()`; holds run-scoped, static data (not conversational state), separate from
     graph state and made available to tools via LangGraph's runtime. Fields: `graph_name: str`
     (required, the Apache Age graph the run's tools operate against), `attached_kb_ids: list[str]`
     (the knowledge base IDs a run's tools may operate against), `session: AsyncSession` (required
     — how tools reach the NodeEmbedding/GraphSchemaRegistry side-tables; needs `model_config =
     ConfigDict(arbitrary_types_allowed=True)` since `AsyncSession` isn't a pydantic type),
     `repository: AgeGraphRepository` (required — how tools reach the live Apache Age graph
     directly, e.g. for relationship traversal, as opposed to the `session`-backed side-tables),
     and `model: Model | None` (embedding provider for tools that vector-search; `None` means such
     tools should raise, matching `GraphSchemaRegistry.vector_search`'s own contract)
   - `tools.py` - tool implementations. Tools access `AgentContext` by adding a
     `runtime: ToolRuntime[AgentContext]` parameter (imported from `langchain.tools`) and reading
     `runtime.context.*`; LangChain injects this argument automatically so it's excluded from the
     tool's schema shown to the model — don't document it in the tool's docstring or list it as a
     model-facing arg. `@tool`-decorated functions require a docstring (LangChain raises
     `ValueError` at decoration time otherwise), and can be `async def` when they need to await a
     model method. `search_schema_registry(query, runtime)` calls
     `GraphSchemaRegistry.vector_search(context.session, query, context.graph_name, context.model,
     knowledge_base_ids=context.attached_kb_ids)` and reshapes each result into a plain dict
     (type/name/description/aliases/properties/source_label/target_label) since tool return values
     must be JSON-serializable, not ORM instances. `search_entities(query, runtime, labels=None)`
     calls `NodeEmbedding.vector_search(context.session, query, context.graph_name, context.model,
     labels=labels)` and reshapes each result into a plain dict (node_id/label/properties) for the
     same JSON-serializability reason. Unlike `search_schema_registry`, it does not scope to
     `context.attached_kb_ids` — `NodeEmbedding.vector_search`'s `knowledge_base_id` filter is a
     single-value equality filter (one knowledge base at a time), not a multi-id overlap filter like
     `GraphSchemaRegistry.vector_search`'s `knowledge_base_ids`, so it can't take the whole
     `attached_kb_ids` list. `get_node_neighbours(node, runtime, relationships=None)` calls
     `await context.repository.get_node_neighbours(context.graph_name, node.id,
     relationship_labels=relationships)` (the repository is fully async — see "Direct Graph Query
     & Async Repository Pattern" below) and reshapes the returned `(source, relationship, target)`
     triplets into a single dict via `node_neighbours_to_dict()`, grouped under the queried node
     rather than repeating it once per relationship (a flat triplet list would echo the same
     node dict — often the largest, since it's the caller's own input — once per relationship,
     wasting tokens in an LLM tool result). `get_node_schema(node, runtime)` is the cheap
     *overview* counterpart: it calls `await context.repository.get_node_schema(context.graph_name,
     node.id)` and reshapes the result via `node_schema_to_dict()` into the distinct relationship
     label / direction / neighbor label combinations plus a `count` per combination. Use it before
     `get_node_neighbours` — it answers "what kinds of things is this node connected to?" without
     returning every neighbor's full property dict. It takes no relationship-label filter on purpose:
     it's what the agent calls *before* it knows which labels matter, and every extra parameter
     enlarges the model-facing tool schema
   - `serializers.py` - `schema_registry_record_to_dict()` / `node_embedding_record_to_dict()` /
     `node_neighbours_to_dict()` / `node_schema_to_dict()`, the ORM-record/agtype-to-plain-dict
     conversions shared by
     `tools.py`'s tool implementations (kept in their own module, not prefixed with `_`, so they're
     importable/testable independent of any `@tool`-decorated function)
   - Intended for: LLM-based agent tools that interact with the knowledge graph

4. **Services** (`src/graphrag_apacheage/services/`)
   - `KnowledgeBaseService`: High-level service for knowledge base operations.
     `upsert_knowledge_base()` is `async def` (awaits the now-fully-async `AgeGraphRepository`)
   - `EmbeddingService` (`services/embedding_service.py`): Computes text embeddings via litellm,
     shared by any ORM model with a vector embedding column

5. **Repositories** (`src/graphrag_apacheage/repositories/`)
   - `AgeGraphRepository`: Data access layer for Apache Age graph operations. Fully async, backed
     by `psycopg` v3's `AsyncConnection`/`AsyncCursor` (not `psycopg2`, which has no async mode).
     Most methods only build and `.execute()` a Cypher query, returning the query string itself
     (used as an audit trail, e.g. by `KnowledgeBaseService.upsert_knowledge_base()`) without
     fetching/parsing results — `graph_exists()` fetches but only checks `(await cursor.fetchone())
     is not None`. `get_node_neighbours()` and `get_node_schema()` are the methods that
     actually fetch and parse real result rows — see "Direct Graph Query & Async Repository
     Pattern" below

### Data Flow

```
JSON File → KnowledgeBase.from_json_file() → get_graph_schema_registry_records(graph_name) → 
  → GraphSchemaRegistry list → GraphSchemaRegistry.upsert_records() → Database

JSON File → KnowledgeBase.from_json_file() → get_node_embedding_records(graph_name) →
  → NodeEmbedding list → NodeEmbedding.upsert_records() (embeds via litellm) → Database
  → NodeEmbedding.vector_search(query, graph_name) → nodes ranked by similarity
```

## Key Patterns & Conventions

### IDs and Identifiers
- **UUID generation**: Node, relationship, and knowledge base IDs are auto-generated as UUIDs if not provided
- Uses `@model_validator(mode="before")` in Pydantic models to ensure IDs exist
- See: `KnowledgeNode.ensure_id()`, `KnowledgeRelationship.ensure_related_ids()`, `KnowledgeBase.ensure_knowledge_base_id()`
- `KnowledgeBase.id` is required by `get_graph_schema_registry_records()` / `get_node_embedding_records()` — both raise `ValueError` when it is falsy. The id is auto-generated when the `id` key is absent from input, but an explicit `"id": null` survives `setdefault` and still raises

### Schema Registry Pattern
- One row per `(graph_name, type, name)` — the same label (e.g. `Driver`) may legitimately be
  defined by more than one knowledge base feeding the same graph, so the match key does **not**
  include the knowledge base id; instead the row is shared and accumulates every contributing
  knowledge base's id
- `GraphSchemaRegistry.upsert_records()` performs smart merging:
  - Creates new records if not found
  - Merges aliases: `existing.aliases = sorted(set(existing.aliases) | set(record.aliases))`
  - Merges properties: `existing.properties = sorted(set(existing.properties) | set(record.properties))`
  - Merges knowledge_base_ids: `existing.knowledge_base_ids = sorted(set(existing.knowledge_base_ids) | set(record.knowledge_base_ids))`
  - Preserves source/target labels if not yet set
- `KnowledgeBase.get_graph_schema_registry_records(graph_name)` extracts schema records
  - Requires `graph_name` parameter (not stored on model, passed to method)
  - Requires `self.id` to be set (raises `ValueError` otherwise); sets `knowledge_base_ids=[self.id]` on each constructed record
  - Returns list of `GraphSchemaRegistry` records for nodes and relationships
- See: `src/graphrag_apacheage/models/graph_schema_registry.py` and `src/graphrag_apacheage/schemas/knowledge_base.py`

### Vector Embedding & Search Pattern
- Both `GraphSchemaRegistry` and `NodeEmbedding` (`models/node_embedding.py`) store a pgvector `embedding` column (`Vector(settings.embedding_dimension).with_variant(JSON, "sqlite")`), sized from the `settings` singleton (`config.py`, `AppSettings.embedding_dimension`, default `1536`) — both ORM models import `settings` directly from `config.py` (not from `embedding_service.py`, and not from an env var) so tests run against SQLite (embedding stored as JSON) while production uses PostgreSQL + pgvector
  - `AppSettings` (`config.py`) is a pydantic `BaseModel` holding all app config, and loads YAML in its constructor: `AppSettings(path)` reads `embedding_dimensions` into `embedding_dimension` and the top-level `models:` list into `models: list[Model]`, so the config file is parsed exactly once at startup. `AppSettings()` (no path) touches no disk and uses field defaults; explicit kwargs (`AppSettings(path, embedding_dimension=768)`) win over the file
  - `config.load_config(path=DEFAULT_CONFIG_PATH)` updates the `settings` singleton's fields **in place** (it does not rebind the module-level name) so modules that already did `from graphrag_apacheage.config import settings` see the loaded values — rebinding would leave them holding a stale object. `main()` in `__init__.py` is the single call site
  - Ordering gotcha: `load_config()` must run before `models/graph_schema_registry.py` or `models/node_embedding.py` are first imported anywhere, since pgvector's `Vector` column size is fixed at class-definition time; a later reload cannot resize an already-defined column
  - The committed `configs/local.yaml` ships `models: []` with a filled-in template in comments. Placeholder/blank entries are deliberately NOT skipped — `auth_mode: ""` fails validation loudly, as does an `api_key_env` naming an unset variable, so misconfiguration surfaces at startup instead of silently yielding a keyless model
  - Import-cycle hazard: `models/graph_schema_registry.py` imports `services.embedding_service`, `services/knowledge_base_service.py` imports `schemas.knowledge_base`, and `schemas/knowledge_base.py` imports back into `models.graph_schema_registry` — a real cycle. It's cut by keeping `models/__init__.py`, `services/__init__.py`, and `repositories/__init__.py` **intentionally empty** (docstring only, no re-exports), so importing one leaf module never runs its siblings as a side effect of `services/__init__.py` (or `models/__init__.py`) executing first. `schemas/`, `agent/`, and `api/` have no `__init__.py` at all, for the same reason. Always import leaf modules directly (`from graphrag_apacheage.services.embedding_service import EmbeddingService`, never `from graphrag_apacheage.services import EmbeddingService`) and never add a re-export to one of these three `__init__.py` files — that's exactly what closes the loop again. If you add a new cross-package module-level import, sanity-check it with `python -c "from graphrag_apacheage.<new_entry_point> import ..."` in a fresh interpreter — pytest's own import order can mask a real cycle
- Embeddings are computed by `EmbeddingService.compute_embeddings(model, texts)` (`services/embedding_service.py`) via `litellm.aembedding()` — both ORM models import `EmbeddingService` from there instead of defining their own copies
  - Takes an explicit `model: Model | None` (see `schemas/model.py`) describing the provider — builds the litellm model string as `f"{model.provider}/{model.name}"`, passes `connection_string` as `api_base`, `api_key.get_secret_value()` as `api_key` when `auth_mode` is `api_key`, and `embedding_dimension` as `dimensions`
  - If `model` is `None` (or `texts` is empty), embedding is skipped entirely (returns `None`) so callers without a configured provider are unaffected — there is no global env var fallback
- Each ORM model builds its own `embedding_text()` (name/description/aliases for `GraphSchemaRegistry`; label + `"key: value"` properties for `NodeEmbedding`) and (re)computes it inside `upsert_records(session, records, model=...)` after merging/updating fields, by calling `EmbeddingService.compute_embeddings(model, texts)`
- `vector_search(session, query, graph_name, model, ..., limit=5)` embeds the query text via the given `model`, then orders rows with pgvector's cosine distance operator: `cls.embedding.cosine_distance(embedding)` — requires PostgreSQL, raises `ValueError` if `model` is `None`
- `NodeEmbedding` rows are keyed by `graph_name` + `knowledge_base_id` + `node_id` (a `UniqueConstraint`), since the same `node_id` may legitimately be contributed by more than one knowledge base feeding the same graph — each combination is stored as its own row. `KnowledgeBase.get_node_embedding_records(graph_name)` builds one unsaved `NodeEmbedding` per node, requiring `self.id` to be set (raises `ValueError` otherwise) and stamping it onto each record as `knowledge_base_id`; `KnowledgeBaseService.upsert_node_embeddings(session, kb, graph_name, model=None)` / `.search_nodes(session, query, graph_name, model, ..., knowledge_base_id=None, ...)` wrap the upsert/search calls and pass `model` straight through (upsert defaults to `None` — skip embedding; search requires a `model`). `NodeEmbedding.vector_search()` / `search_nodes()` take an optional `knowledge_base_id` (singular, equality filter) to scope a search to one knowledge base, and an optional `labels: list[str] | None` filtered via `cls.label.in_(labels)` (only applied when the list is non-empty) — plural because a caller (e.g. the `search_entities` agent tool) may want nodes matching any of several labels in one query, unlike the single-knowledge-base-at-a-time `knowledge_base_id` filter
- `GraphSchemaRegistry.vector_search()` takes an optional `knowledge_base_ids: list[str] | None` (plural, overlap filter) since a schema row's `knowledge_base_ids` is shared across contributing knowledge bases by design. Implemented as PostgreSQL-only: `cast(cls.knowledge_base_ids, JSONB).op("?|")(array(knowledge_base_ids))` — casts the plain-JSON column to `JSONB` at query time (no column-type change needed) and uses jsonb's `?|` "any of these strings present" operator; only applied when the list is non-empty, and covered by a compiled-SQL test the same way as the cosine-distance test (`FakeSession` capturing the statement, compiled against `postgresql.dialect()`) since `?|` doesn't run on SQLite
- Tests monkeypatch `embedding_service.litellm.aembedding` (import the module as `embedding_service`, not the individual ORM model modules) and pass a `Model` built via a small `_embedding_model()` test helper, to avoid real API calls
- See: `src/graphrag_apacheage/services/embedding_service.py`, `src/graphrag_apacheage/schemas/model.py`, `src/graphrag_apacheage/models/node_embedding.py`, and `tests/test_embedding_service.py` / `tests/test_node_embedding_model.py`

### Direct Graph Query & Async Repository Pattern
- `AgeGraphRepository` (`repositories/age_graph_repository.py`) is fully async, backed by `psycopg` v3's `AsyncConnection`/`AsyncCursor` — every method is `async def`. This replaced an earlier synchronous `psycopg2`-based repository, since `psycopg2` has no async mode at all; `KnowledgeBaseService.upsert_knowledge_base()` is `async def` too, since it awaits repository calls internally
- Most methods only build and `.execute()` a Cypher query, returning the query string itself (used as an audit trail, e.g. by `upsert_knowledge_base()`) without fetching/parsing results — `graph_exists()` is the one exception that fetches, but only checks `(await cursor.fetchone()) is not None`
- `get_node_neighbours(graph_name, node_id, relationship_labels=None)` is the first method that actually fetches and parses real result rows: it matches a node via its app-level `id` property (the same property `create_node`/`create_relationship` set — not Apache Age's own internal vertex id/graphid), traverses relationships in both directions (`MATCH (a {"id": ...})-[r]-(b)`), and returns a de-duplicated `list[tuple[dict, dict, dict]]` of `(source, relationship, target)`
  - Apache Age returns each vertex/edge `agtype` column as a string suffixed with its Cypher type, e.g. `{"id": ..., "label": ..., "properties": {...}}::vertex` / `...::edge`. `_parse_agtype()` strips the `::vertex`/`::edge` suffix and `json.loads`es the remainder
  - De-duplicates on the edge's own internal `id` (not on a `(source, label, target)` tuple), since Apache Age can return the same physical edge twice for an undirected `()-[r]-()` pattern; a source/label/target-based key would incorrectly collapse legitimate parallel edges, since Apache Age is a multigraph
  - Source/target are oriented by comparing each vertex's internal `id` to the edge's `start_id`/`end_id`, since the queried node isn't always bound to the pattern's first variable (`a`)
- `get_node_schema(graph_name, node_id)` returns the *shape* of a node's neighborhood rather than
  its contents: a `list[tuple[relationship_label, direction, neighbor_label, count]]`. It runs one
  query per direction — `MATCH (a {"id": ...})-[r]->(b)` then `<-[r]-` — each
  `RETURN type(r), label(b), count(*)`, so direction comes from which query produced the row (no
  `start_id`/`end_id` comparison needed) and the *database* does the counting, meaning a high-degree
  node costs a handful of rows instead of one per relationship. Entries are sorted by
  `(relationship_label, neighbor_label)` within each direction, outgoing first, since the database
  guarantees no row order. A self-loop legitimately appears in both directions
  - The columns here are bare agtype *scalars*, not `::vertex`/`::edge` payloads. `_parse_agtype()`
    handles both (the suffix strip is a no-op for scalars), so its return type is `Any`, not `dict`
  - Unverified against a live Apache Age instance: `label(b)` and `count(*)` with implicit grouping.
    `type(r)` is already used by shipped code. Unit tests use fake cursors, so they pin the query
    string and the parsing, not that Age accepts the Cypher. If `label(b)` turns out to be
    unsupported on the target Age version, the fallback is to return `b` and read `b["label"]` in
    Python — which loses the DB-side aggregation and forces a client-side `count`
- `agent/tools.py`'s `get_node_neighbours` tool wraps this repository method and reshapes the triplets via `agent/serializers.py`'s `node_neighbours_to_dict(node_id, label, properties, triplets)`, which drops Apache Age's internal integer ids (keeping only the app-level UUID `id` pulled out of each vertex's `properties`) and groups results under the queried node once — `{"node": {...}, "relationships": [{"label", "properties", "direction", "neighbor"}, ...]}` — with `direction` ("outgoing"/"incoming") replacing a repeated source/target pair per entry, since a flat triplet-per-relationship list would echo the queried node's full dict once per relationship
- No code in this repo yet constructs a real `psycopg.AsyncConnection` or wires a live `AgeGraphRepository` into `AgentContext` (`api/app.py` is empty) — this is a known, pre-existing gap; the async conversion makes `AgentContext`/`AgeGraphRepository` async-ready for whenever that wiring is added, it doesn't add the wiring itself
- See: `src/graphrag_apacheage/repositories/age_graph_repository.py`, `src/graphrag_apacheage/agent/tools.py`, `src/graphrag_apacheage/agent/serializers.py`, and the `test_age_graph_repository_get_node_neighbours_*` tests in `tests/test_graph_registry_model.py`

### Validation & Constraints
- Type constraint in GraphSchemaRegistry: `type IN ('node', 'relationship')` via CheckConstraint
- Tests verify this constraint is enforced: `test_graph_registry_type_accepts_only_node_or_relationship()`
- `NodeEmbedding` has a `UniqueConstraint("graph_name", "knowledge_base_id", "node_id")` — one row per node per knowledge base per graph
- `KnowledgeBase.get_graph_schema_registry_records()` / `get_node_embedding_records()` raise `ValueError` if `self.id` is falsy

## Common Tasks

### Adding a New Schema Type
1. Update `SchemaType` enum in `models/graph_schema_registry.py`
2. Add CheckConstraint to `GraphSchemaRegistry.__table_args__`
3. Add test in `tests/test_graph_registry_model.py`

### Loading and Registering a Knowledge Base
```python
from sqlalchemy.ext.asyncio import AsyncSession

kb = KnowledgeBase.from_json_file("path/to/kb.json")
# kb.id must be set — both getters raise ValueError otherwise
schema_records = kb.get_graph_schema_registry_records("my_age_graph")  # graph_name required
node_records = kb.get_node_embedding_records("my_age_graph")

embedding_model = Model(
    name="text-embedding-3-small",
    provider="openai",
    connection_string="https://api.openai.com/v1",
    auth_mode=AuthMode.API_KEY,
    api_key="...",
    type=[ModelType.EMBEDDING],
    embedding_dimension=1536,
)

# upsert_records() is async (litellm embedding calls are awaited internally)
async with AsyncSession(engine) as session:
    await GraphSchemaRegistry.upsert_records(session, schema_records, model=embedding_model)
    await NodeEmbedding.upsert_records(session, node_records, model=embedding_model)
    await session.commit()
```

### Adding Vector Search for a New Entity
1. Subclass `Base` from `models/base.py` (don't redefine a new declarative base)
2. Add an `embedding` column: `Vector(settings.embedding_dimension).with_variant(JSON, "sqlite")` (import `settings` from `config.py`)
3. Implement `embedding_text()` to build the text that gets embedded
4. Implement `upsert_records(session, records, model=None)` and `vector_search(session, query, graph_name, model, ...)` following the `NodeEmbedding` pattern (call `EmbeddingService.compute_embeddings(model, texts)` from `services/embedding_service.py` — don't duplicate the litellm call)
5. Add tests mirroring `tests/test_node_embedding_model.py` (round-trip on SQLite, skip-when-model-not-provided, litellm-mocked upsert with a `Model` built via a test helper, cosine-distance statement via a fake async session)
6. Ensure `config.load_config()` runs before the new model module is first imported, otherwise the column is sized from `AppSettings`' default rather than the config file

### Testing New Features
- Use in-memory SQLite for fast tests: `create_engine("sqlite:///:memory:")`
- See: `tests/test_graph_registry_model.py` for patterns
- Run tests: `pytest tests/`

## Development Setup

### Required Tools
- Python 3.14+
- uv (package manager, configured in pyproject.toml)
- pytest (for testing)

### Key Files
- `pyproject.toml` - project metadata, dependencies, build config
- `src/graphrag_apacheage/` - main source directory
- `tests/test_graph_registry_model.py` - test suite (schema registry, general KnowledgeBase/service behavior, and `AgeGraphRepository` incl. `get_node_neighbours`)
- `tests/test_node_embedding_model.py` - test suite for `NodeEmbedding` and node vector search
- `tests/test_embedding_service.py` - test suite for the shared `EmbeddingService`
- `tests/test_tools.py` - test suite for `agent/tools.py`'s `@tool`-decorated functions
- `tests/test_serializers.py` - test suite for `agent/serializers.py`'s dict-conversion helpers
- `dummy_data/f1_kb.json` - example knowledge base (Formula 1)

### Running Tests
```bash
pytest tests/
```

### Project Dependencies
- **pydantic** (>=2.13.5): Data validation and serialization
- **sqlalchemy[asyncio]** (>=2.0.42): ORM and database abstraction (async engine/session)
- **psycopg[binary]** (>=3.2): Async PostgreSQL/Apache Age connection (`AgeGraphRepository` is fully async via psycopg3's `AsyncConnection`/`AsyncCursor`)
- **pgvector** (>=0.5.0): `Vector` column type for embedding storage/cosine search
- **litellm** (>=1.99.0): Provider-agnostic embedding calls (`litellm.aembedding`); called only when a `Model` is passed to `EmbeddingService.compute_embeddings()`
- Dev-only: **aiosqlite** for async SQLite tests

## Important Notes


### Testing Strategy
- Tests use SQLite in-memory databases (no PostgreSQL required for unit tests)
- Tests validate schema structure, constraints, and upsert logic
- Key tests:
  - `test_knowledge_base_parses_json_and_upserts_registry_rows()` - end-to-end JSON→DB flow
  - `test_graph_registry_type_accepts_only_node_or_relationship()` - constraint validation
  - `test_knowledge_base_graph_name_is_provided_to_service_not_stored()` - graph_name parameter pattern
  - `test_upsert_node_embeddings_computes_embedding_via_litellm_when_configured()` - monkeypatches `litellm.aembedding` (via `embedding_service.litellm`, shared by both embedding models) and passes a `Model` to avoid real API calls
  - `test_vector_search_embeds_query_and_builds_cosine_distance_statement()` - asserts on the compiled `postgresql` dialect SQL (via a fake async session) since pgvector's `<=>` operator can't run on SQLite
  - `test_vector_search_filters_by_multiple_labels_when_provided()` - asserts `NodeEmbedding.vector_search(..., labels=[...])` compiles to a `label IN (...)` filter (same fake-session/compiled-SQL approach)
  - `test_upsert_node_embeddings_keeps_separate_rows_per_knowledge_base()` - same `graph_name`/`node_id` from two different `knowledge_base_id`s upserts to 2 rows, not 1
  - `test_upsert_records_merges_knowledge_base_ids_for_same_label_across_knowledge_bases()` - same label from two knowledge bases upserts to 1 shared row with both ids in `knowledge_base_ids`
  - `test_age_graph_repository_get_node_neighbours_orients_source_target_via_edge_start_end_ids()` - regression test that source/target come from the edge's own `start_id`/`end_id`, not from assuming the queried node is always bound to the pattern's first variable
  - `test_age_graph_repository_get_node_neighbours_deduplicates_repeated_edge_rows()` - the same physical edge returned twice by a fake cursor still yields one triplet
  - `test_age_graph_repository_get_node_schema_queries_both_directions_by_id_property()` - asserts the outgoing `-[r]->` and incoming `<-[r]-` queries are both issued. Uses `_QueuedRowsConnection`, a fake that serves a *different* row batch per `execute` and records every query — `_RowsConnection` replays one fixed row set and so cannot represent a two-query method
  - `test_age_graph_repository_get_node_schema_orders_entries_deterministically()` - unordered fake rows still come back sorted per direction, outgoing before incoming
- Example data: `dummy_data/f1_kb.json` (Formula 1 knowledge base, with a stable top-level `id` so re-ingesting the file is idempotent)

### Type System
- Uses Python 3.10+ type hints throughout (e.g., `list[str]`, `dict[str, Any]`, `str | None`)
- Pydantic models with `BaseModel` for runtime validation
- SQLAlchemy 2.0 style with `Mapped` type hints for ORM columns

## Codebase Structure for Agents

### When Adding Features
1. Define Pydantic models in `schemas/` for data structures
2. Define SQLAlchemy models in `models/` for database persistence
3. Add validation logic via `@model_validator` decorators
4. Write tests in `tests/` using in-memory SQLite
5. Document in this file if introducing new patterns

### When Debugging
- Check test files for expected behavior patterns
- Use `pytest -v` for detailed test output
- Verify type hints with static checkers if available
