# Agent Customization for graphrag-apacheage

> **Sync note:** This file and `AGENTS.md` must stay identical. Edit one, copy change to other, same commit.
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
     model method. Both `search_schema_registry` and `search_entities` raise `ValueError` up front
     when `query.strip()` is empty, the same fail-fast convention `get_node_schema`/
     `get_node_neighbours` use for a missing `node.id` — an empty query would otherwise reach
     `EmbeddingService.compute_embeddings()` and either waste a real embedding call on blank text or
     (with no `model` configured) silently return no results, instead of surfacing the bad input at
     the tool boundary. `search_schema_registry(query, runtime)` calls
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
     triplets into a single dict via `AgentSerializer.node_neighbours_to_dict()`, grouped under the queried node
     rather than repeating it once per relationship (a flat triplet list would echo the same
     node dict — often the largest, since it's the caller's own input — once per relationship,
     wasting tokens in an LLM tool result). `get_node_schema(node, runtime)` is the cheap
     *overview* counterpart: it calls `await context.repository.get_node_schema(context.graph_name,
     node.id)` and reshapes the result via `AgentSerializer.node_schema_to_dict()` into the distinct relationship
     label / direction / neighbor label combinations plus a `count` per combination. Use it before
     `get_node_neighbours` — it answers "what kinds of things is this node connected to?" without
     returning every neighbor's full property dict. It takes no relationship-label filter on purpose:
     it's what the agent calls *before* it knows which labels matter, and every extra parameter
     enlarges the model-facing tool schema
   - `serializers.py` - `AgentSerializer`, a class of `@staticmethod`/`@classmethod` conversions
     (`schema_registry_record_to_dict()` / `node_embedding_record_to_dict()` /
     `node_neighbours_to_dict()` / `node_schema_to_dict()`) shared by `tools.py`'s tool
     implementations. Grouped as one class purely for a single, discoverable import surface — none
     hold or need instance state. Kept in their own module, not prefixed with `_`, so they're
     importable/testable independent of any `@tool`-decorated function
   - `prompts.py` - `GRAPH_AGENT_SYSTEM_PROMPT`, the agent's system prompt. Its own module so
     replacing the prompt is a one-line change in one file: `deep_agent.py` imports the constant and
     never inlines prompt text, and `tests/test_deep_agent.py` asserts prompt *identity*
     (`captured["system_prompt"] is GRAPH_AGENT_SYSTEM_PROMPT`), never prompt content, so swapping
     the text in cannot turn a test red. The shipped text is a deliberate **placeholder** — usable
     (it encodes the schema-discovery -> `search_entities` -> `get_node_schema` ->
     `get_node_neighbours` call order the tools are designed around) but not the final prompt
   - `get_node_schema(node, runtime)` enriches `AgeGraphRepository.get_node_schema()`'s
     `(relationship_label, direction, neighbor_label, count)` tuples with property-**name** lists
     (not values) for the node's own label, each distinct relationship label, and each distinct
     neighbor label appearing in the entries — sourced from `GraphSchemaRegistry` via its
     `get_properties_by_name(session, graph_name, names, type=None)` classmethod, not from the live
     Apache Age graph, since `GraphSchemaRegistry.properties` already **is** a property-name list
     (see "Schema Registry Pattern"); no new Cypher is needed and the already-fragile,
     unverified-against-a-live-instance `get_node_schema` Cypher (see "Direct Graph Query & Async
     Repository Pattern") stays untouched. The node's own live `node.properties` values (the
     `KnowledgeNode` argument) are deliberately **not** used for this — the agent typically calls
     this tool precisely because it doesn't know the node's real property values yet, so it may pass
     a `KnowledgeNode` with `properties={}`. Three separate `get_properties_by_name` calls are made
     (one per `SchemaType`, since `type` is a single value, not an overlap filter): one for
     `[node.label]` (`SchemaType.NODE`), one for the distinct relationship labels across entries
     (`SchemaType.RELATIONSHIP`), one for the distinct neighbor labels across entries
     (`SchemaType.NODE`) — passed to `AgentSerializer.node_schema_to_dict()` as
     `node_properties`/`relationship_properties`/`neighbor_properties`, the latter two dicts keyed
     by label since the same label can repeat across entries (once per direction, or against
     multiple neighbor labels). A label absent from the registry (e.g. never upserted) is simply
     omitted from `get_properties_by_name()`'s result dict, so its properties list renders as `[]`
     rather than raising
   - `chat_model.py` - `build_chat_model(model, /, **overrides)`, mapping a configured `Model`
     (`schemas/model.py`) to a `ChatLiteLLM` (`langchain-litellm`). Mirrors
     `EmbeddingService.compute_embeddings()`'s `Model` -> litellm kwarg mapping exactly —
     `f"{provider}/{name}"` as the model string, `connection_string` as `api_base`,
     `api_key.get_secret_value()` only when `auth_mode` is `api_key` — so chat and embedding calls
     read the same config the same way. `embedding_dimension` is deliberately **not** forwarded (no
     chat-completion meaning), and nothing else is set by default, so provider defaults apply unless
     a caller passes `**overrides` (`temperature`, `max_tokens`, `profile`). The `model` parameter is
     **positional-only** (`/`) because `model` is also `ChatLiteLLM`'s own field name — without the
     marker, `build_chat_model(cfg, model=...)` raises `TypeError: got multiple values for argument
     'model'` instead of overriding the model string. Note the deviation: the convention-consistent
     home for this is `services/chat_model_service.py` as a `ChatModelService` mirroring
     `EmbeddingService`, since nothing about it is agent-specific. It lives in `agent/` because it
     currently has exactly one caller; move it (file move + one import line in `deep_agent.py`) as
     soon as a non-agent caller appears
   - `deep_agent.py` - `build_deep_agent(chat_model, *, tools, middleware, system_prompt, name)`,
     the single place the agent is assembled. See "Deep Agent Assembly Pattern" below
   - `GRAPH_TOOLS` (in `tools.py`) - the ordered list of the four tools handed to the agent. It lives
     in `tools.py`, the leaf module that owns the tools, **not** in an `agent/__init__.py`: `agent/`
     has no `__init__.py` at all on purpose (see the import-cycle note under "Vector Embedding &
     Search Pattern"), so the aggregate has to sit beside what it aggregates. Import it as
     `from graphrag_apacheage.agent.tools import GRAPH_TOOLS`

4. **Services** (`src/graphrag_apacheage/services/`)
   - `KnowledgeBaseService`: High-level service for knowledge base operations. Every method is
     `async def` (awaits the fully-async `AgeGraphRepository` and/or the awaited litellm embedding
     calls). `upsert_knowledge_base()` / `delete_knowledge_base()` are the orchestrating pair that
     keep the graph and both side-tables in sync — see "Knowledge Base Lifecycle Pattern" below
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
JSON File → KnowledgeBase.from_json_file() → KnowledgeBaseService.upsert_knowledge_base(
    session, kb, graph_name, model) → 3 writes in one call:
  1. nodes/relationships → AgeGraphRepository.create_node()/create_relationship() → Apache Age graph
  2. get_graph_schema_registry_records(graph_name) → GraphSchemaRegistry.upsert_records()
  3. get_node_embedding_records(graph_name) → NodeEmbedding.upsert_records() (embeds via litellm)

KnowledgeBaseService.delete_knowledge_base(session, kb_id, graph_name) → the inverse:
  1. NodeEmbedding rows (kb_id, graph_name) → node ids → repository.delete_node() (DETACH DELETE)
  2. DELETE those NodeEmbedding rows
  3. GraphSchemaRegistry: drop kb_id from knowledge_base_ids; delete rows left with none

NodeEmbedding.vector_search(query, graph_name) → nodes ranked by similarity
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
  - Both node and relationship records always get `aliases=[]` — there is deliberately no alias
    source for either yet (a node's own `id` previously leaked into `aliases` by mistake, and
    relationship records were seeding `aliases` with `relationship.label`, which is redundant with
    `name`). Revisit once there's a real alias source (e.g. alternate display names)
- `GraphSchemaRegistry.get_properties_by_name(session, graph_name, names, type=None)` looks up the
  stored `properties` list for a batch of names in one query (`name.in_(names)`, optionally filtered
  by `type`), returning a `dict[name, list[str]]` that omits any name with no matching row (rather
  than mapping it to `[]`) — the caller decides the default for a schema-less label. This is what
  `agent/tools.py`'s `get_node_schema` tool uses to attach property-**name** lists to its neighborhood
  summary (see the `agent/tools.py` bullet under "Agents" above); the same `type` value is shared
  across all `names` passed in one call, so a caller needing both node and relationship labels'
  properties makes two calls, not one
- See: `src/graphrag_apacheage/models/graph_schema_registry.py` and `src/graphrag_apacheage/schemas/knowledge_base.py`

### Knowledge Base Lifecycle Pattern
- `KnowledgeBaseService` owns the whole lifecycle of one knowledge base in one graph. There are two
  orchestrating methods; the four single-concern methods they call
  (`upsert_graph_schema_registry()`, `delete_graph_schema_registry()`, `upsert_node_embeddings()`,
  `search_nodes()`) stay public so a caller can drive one side-table alone
- `upsert_knowledge_base(session, knowledge_base, graph_name, model=None)` does three writes:
  the graph (`create_node`/`create_relationship` + `repository.commit()`), then
  `GraphSchemaRegistry.upsert_records()`, then `NodeEmbedding.upsert_records()`. It returns only the
  list of executed Cypher queries (the graph audit trail) — call the single-concern methods directly
  if you need the persisted side-table records back
- `delete_knowledge_base(session, knowledge_base_id, graph_name)` is the inverse and takes an **id**,
  not a `KnowledgeBase`: at delete time the source JSON is usually long gone. It gets the node ids
  to delete from the knowledge base's own `NodeEmbedding` rows, which are the service's record of
  what it wrote to the graph — so a knowledge base written by something *other* than
  `upsert_knowledge_base()` (no `NodeEmbedding` rows) will not have its graph nodes removed
  - Nodes are removed with `repository.delete_node()`, i.e. `DETACH DELETE`, so relationships go
    with their nodes and no separate relationship pass is needed
  - Schema registry adjustment removes `knowledge_base_id` from each row's `knowledge_base_ids` and
    deletes only the rows left with no contributing knowledge base, since a label may be defined by
    several knowledge bases feeding one graph (see "Schema Registry Pattern")
  - **Known limitation:** a surviving shared row keeps the aliases and properties the deleted
    knowledge base contributed — the merge in `upsert_records()` is lossy and cannot be attributed
    back per knowledge base. Re-upsert the remaining knowledge bases if an exact schema is required
  - `delete_graph_schema_registry()` filters rows in **Python**, not SQL: `knowledge_base_ids` is a
    plain JSON column and a graph holds one registry row per label, so the scan is cheap and works
    on SQLite. Do *not* reach for the jsonb `?|` operator `GraphSchemaRegistry.vector_search()` uses
    — that's PostgreSQL-only and would make these paths untestable on SQLite
- `create_graph(graph_name)` / `delete_graph(session, graph_name)` are the graph lifecycle pair.
  Both live on the service so callers never mix service and repository calls for the same concern,
  and both return `None` when there was nothing to do (graph already exists / graph already gone).
  `AgeGraphRepository` keeps its own raw `create_graph()`/`delete_graph()` pair — the service
  methods delegate to them; the asymmetry to avoid is a *layer* that owns one half of a pair
  - `create_graph()` takes no `session` on purpose: a new graph has no side-table rows, so there is
    nothing to create alongside it. Reusing a graph name dropped outside this service is the one gap
    — call `delete_graph()` first to clear any orphaned rows
- `delete_graph(session, graph_name)` drops the Apache Age graph
  (cascading, so no per-node `DETACH DELETE` pass is needed) and then deletes **all**
  `NodeEmbedding` and `GraphSchemaRegistry` rows for that graph. Registry rows are deleted outright
  rather than adjusted, unlike `delete_knowledge_base()` — the graph they describe is gone, so no
  contributing knowledge base has a remaining claim
  - A missing graph is deliberately **not** an error: dropping a graph is exactly what orphans the
    side-tables, so the rows are cleaned up either way. Returns the drop query, or `None` when the
    graph didn't exist and only the side-tables were cleaned
  - The side-table cleanup lives on the service and not on `AgeGraphRepository.delete_graph()` even though the
    repository's psycopg connection *could* run the `DELETE`s (same database) — and in one
    transaction with the drop, which this split does not get. The blocker is imports: naming the
    tables via `NodeEmbedding.__tablename__` would make `repositories/age_graph_repository.py`
    import the pgvector ORM models, and `__init__.py` imports that repository at **module level**,
    before `main()` calls `load_config()` — so the embedding column would be sized from defaults.
    Avoiding that means duplicating `"node_embedding"`/`"graph_registry"` as string literals, and
    the cleanup would only be testable as pinned query strings against a fake cursor instead of as
    real row deletion on SQLite
- Transaction split (all three methods): the **graph** connection is committed inside the method
  (`repository.commit()`), the SQLAlchemy `session` is only flushed — committing it is the caller's
  job, so a caller can batch several knowledge bases into one side-table transaction. The two stores
  are not in a shared transaction, so a failure between them can leave the graph ahead of the
  side-tables; re-running the upsert is idempotent and recovers
- See: `src/graphrag_apacheage/services/knowledge_base_service.py` and the
  `test_delete_knowledge_base_*` / `test_delete_graph_*` tests in `tests/test_graph_registry_model.py`

### Vector Embedding & Search Pattern
- Both `GraphSchemaRegistry` and `NodeEmbedding` (`models/node_embedding.py`) store a pgvector `embedding` column (`Vector(settings.embedding_dimension).with_variant(JSON, "sqlite")`), sized from the `settings` singleton (`config.py`, `AppSettings.embedding_dimension`, default `1536`) — both ORM models import `settings` directly from `config.py` (not from `embedding_service.py`, and not from an env var) so tests run against SQLite (embedding stored as JSON) while production uses PostgreSQL + pgvector
  - `AppSettings` (`config.py`) is a pydantic `BaseModel` holding all app config, and loads YAML in its constructor: `AppSettings(path)` reads `embedding_dimensions` into `embedding_dimension` and the top-level `models:` list into `models: list[Model]`, so the config file is parsed exactly once at startup. `AppSettings()` (no path) touches no disk and uses field defaults; explicit kwargs (`AppSettings(path, embedding_dimension=768)`) win over the file
  - `config.load_config(path=DEFAULT_CONFIG_PATH)` updates the `settings` singleton's fields **in place** (it does not rebind the module-level name) so modules that already did `from graphrag_apacheage.config import settings` see the loaded values — rebinding would leave them holding a stale object. `main()` in `__init__.py` is the single call site
  - Ordering gotcha: `load_config()` must run before `models/graph_schema_registry.py` or `models/node_embedding.py` are first imported anywhere, since pgvector's `Vector` column size is fixed at class-definition time; a later reload cannot resize an already-defined column
  - The committed `configs/local.yaml` ships `models: []` with a filled-in template in comments. Placeholder/blank entries are deliberately NOT skipped — `auth_mode: ""` fails validation loudly, as does an `api_key_env` naming an unset variable, so misconfiguration surfaces at startup instead of silently yielding a keyless model
  - Import-cycle hazard: `models/graph_schema_registry.py` imports `services.embedding_service`, `services/knowledge_base_service.py` imports `schemas.knowledge_base`, and `schemas/knowledge_base.py` imports back into `models.graph_schema_registry` — a real cycle. It's cut by keeping `models/__init__.py`, `services/__init__.py`, and `repositories/__init__.py` **intentionally empty** (docstring only, no re-exports), so importing one leaf module never runs its siblings as a side effect of `services/__init__.py` (or `models/__init__.py`) executing first. `schemas/`, `agent/`, and `api/` have no `__init__.py` at all, for the same reason. Always import leaf modules directly (`from graphrag_apacheage.services.embedding_service import EmbeddingService`, never `from graphrag_apacheage.services import EmbeddingService`) and never add a re-export to one of these three `__init__.py` files — that's exactly what closes the loop again. If you add a new cross-package module-level import, sanity-check it with `python -c "from graphrag_apacheage.<new_entry_point> import ..."` in a fresh interpreter — pytest's own import order can mask a real cycle. `agent/deep_agent.py` imports `agent/tools.py` and so inherits the `load_config()`-before-import constraint too; sanity-check it with `python -c "from graphrag_apacheage.agent.deep_agent import build_deep_agent"` in a fresh interpreter
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
- Connection setup gotcha: every new Postgres session must run `SET search_path = ag_catalog, "$user", public;` before any `ag_catalog.*` call — AGE's internal DDL (e.g. the btree index it creates using its own `graphid_ops` operator class) resolves operator classes via `search_path`, not via schema-qualification of the calling query. Skipping this raises `psycopg.errors.UndefinedObject: operator class "graphid_ops" does not exist for access method "btree"` on `create_graph()`. On Azure-hosted Postgres (detectable via `"database.azure.com" in host`), the `age` extension is pre-loaded via server-side config; on self-hosted/other clouds, run `LOAD 'age';` before setting `search_path`. `create_connection()` in `__init__.py` handles both cases automatically
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
- `agent/tools.py`'s `get_node_neighbours` tool wraps this repository method and reshapes the triplets via `agent/serializers.py`'s `AgentSerializer.node_neighbours_to_dict(node_id, label, properties, triplets)`, which drops Apache Age's internal integer ids (keeping only the app-level UUID `id` pulled out of each vertex's `properties`) and groups results under the queried node once — `{"node": {...}, "relationships": [{"label", "properties", "direction", "neighbor"}, ...]}` — with `direction` ("outgoing"/"incoming") replacing a repeated source/target pair per entry, since a flat triplet-per-relationship list would echo the queried node's full dict once per relationship
- No code in this repo yet constructs a real `psycopg.AsyncConnection` or wires a live `AgeGraphRepository` into `AgentContext` (`api/app.py` is empty) — this is a known, pre-existing gap; the async conversion makes `AgentContext`/`AgeGraphRepository` async-ready for whenever that wiring is added, it doesn't add the wiring itself
- See: `src/graphrag_apacheage/repositories/age_graph_repository.py`, `src/graphrag_apacheage/agent/tools.py`, `src/graphrag_apacheage/agent/serializers.py`, and the `test_age_graph_repository_get_node_neighbours_*` tests in `tests/test_graph_registry_model.py`

### Deep Agent Assembly Pattern
- `agent/deep_agent.py`'s `build_deep_agent()` is the **only** place the agent graph is built. It
  calls `deepagents.create_deep_agent()` with `GRAPH_TOOLS`, `GRAPH_AGENT_SYSTEM_PROMPT`,
  `context_schema=AgentContext`, and `middleware=[TodoListMiddleware(), *middleware]` — deepagents'
  default stack (filesystem, subagents, summarization, tool-call patching) plus the opt-in todo
  list. `TodoListMiddleware` comes from `langchain.agents.middleware`, **not** from deepagents, and
  is not in deepagents' base stack; it contributes the `write_todos` tool
- `chat_model` is typed `Model | BaseChatModel`. The `Model` branch is the production path (config
  file -> `build_chat_model()` -> `ChatLiteLLM`); the `BaseChatModel` branch lets a caller inject a
  pre-tuned model and lets tests compile the real graph against a `GenericFakeChatModel` with no
  network and no credentials — that single `isinstance` check is what makes the factory
  unit-testable. A model is **always required**: `create_deep_agent(model=None)` falls back to
  `ChatAnthropic` with a deprecation warning, so `build_deep_agent` never forwards `None` and
  `chat_model` must never be given a default
- The chat model is a **construction-time** dependency and is deliberately *not* on `AgentContext`.
  `AgentContext` holds invoke-time, run-scoped data; the chat model is bound into the compiled graph
  (and into the summarization middleware and the general-purpose subagent) at build time, so a
  `chat_model` field there would be read by nothing and could not change which model the graph
  calls. This also keeps `AgentContext.model` unambiguous — it is the *embedding* provider, only. If
  a per-run model override is ever needed, the idiomatic answer is a `@wrap_model_call` middleware
  reading `runtime.context`, and *that* commit is the one that should add `AgentContext.chat_model`
  alongside its consumer
- Run-scoped data is supplied per invocation, not at build time:
  ```python
  agent = build_deep_agent(chat_model_config)  # once, at startup
  result = await agent.ainvoke(
      {"messages": [{"role": "user", "content": "who drives for Mercedes?"}]},
      context=AgentContext(
          graph_name="demo_graph", attached_kb_ids=["kb-1"],
          session=session, repository=repository, model=embedding_model,
      ),
  )
  ```
- **Ordering gotcha (inherited):** `deep_agent.py` imports `agent/tools.py`, which imports both
  pgvector ORM models, so *importing `agent/deep_agent.py` sizes the embedding columns*.
  `config.load_config()` must therefore run before `agent/deep_agent.py` (or `agent/tools.py`) is
  first imported anywhere. The specific trap for the still-empty `api/app.py`: a module-level
  `from graphrag_apacheage.agent.deep_agent import build_deep_agent` with `load_config()` in a
  FastAPI `lifespan` handler runs in the **wrong** order — module imports resolve before any startup
  hook. Load config before the first agent/model import, the way `__init__.py`'s `main()` does
- `checkpointer` and `store` are deliberately **not** exposed yet (conversation persistence and
  long-term memory are planned separately), so every `ainvoke` starts from an empty message list.
  Neither are `subagents`, `skills`, `memory`, `permissions`, `backend`, `interrupt_on`,
  `response_format`, `state_schema`, `debug`, `cache` — promote each to a keyword-only argument when
  a caller actually needs it, rather than adding a `**kwargs` passthrough
- `backend` is left at deepagents' default `StateBackend()` (`deepagents/graph.py:637`), so the
  agent's `read_file`/`write_file` sandbox lives **inside LangGraph state** — it has no host
  filesystem access. A consequence worth knowing: `StateBackend` does not implement
  `SandboxBackendProtocol`, but the `execute` (shell) tool is still advertised to the model and
  simply returns an error message when called. It costs a tool slot and can waste a turn; pass a
  sandbox backend if you actually want execution, or `tools=` restriction if you want it gone
- `subagents` is unset. deepagents still auto-inserts its general-purpose subagent (so the `task`
  tool exists), which inherits the same `AgentContext` — meaning a subagent and its parent share one
  `AsyncSession`. `task` is sequential today, so this is latent rather than live, but a future
  concurrent subagent would need its own session, not a shared one
- deepagents' harness profiles key off the model's provider/identifier, and nothing matches
  `ChatLiteLLM` (litellm identifiers look like `openai/gpt-4o`, with a slash, not `openai:gpt-4o`),
  so no profile applies: no `base_system_prompt`, no `system_prompt_suffix`, no tool description
  overrides, no excluded tools. `GRAPH_AGENT_SYSTEM_PROMPT` is therefore the whole authored system
  prompt. Relatedly, `ChatLiteLLM.profile` defaults to `None`, so `create_summarization_middleware`
  falls back to its conservative fixed token trigger instead of a fraction of the real context
  window — for a smaller-context model, pass `profile={"max_input_tokens": N}` through
  `build_chat_model(cfg, profile=...)`, or hand a configured summarization middleware in via
  `middleware=`
- deepagents hard-depends on `langchain-anthropic` and `langchain-google-genai` (not optional
  extras): `graph.py` imports `ChatAnthropic` at module scope and always appends
  `AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")`. Both are pure-Python and
  no Anthropic/Google credentials are needed as long as a model is always passed explicitly. The
  caching middleware no-ops for non-`ChatAnthropic` models, so routing to Anthropic *through
  litellm* forgoes prompt caching
- See: `src/graphrag_apacheage/agent/deep_agent.py`, `agent/chat_model.py`, `agent/prompts.py`,
  `agent/tools.py` (`GRAPH_TOOLS`), and `tests/test_deep_agent.py` / `tests/test_chat_model.py`

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

kb = KnowledgeBase.from_json_file("path/to/kb.json")  # kb.id must be set

embedding_model = Model(
    name="text-embedding-3-small",
    provider="openai",
    connection_string="https://api.openai.com/v1",
    auth_mode=AuthMode.API_KEY,
    api_key="...",
    type=[ModelType.EMBEDDING],
    embedding_dimension=1536,
)

service = KnowledgeBaseService(repository)
await service.create_graph("my_age_graph")  # no-op if it already exists

async with AsyncSession(engine) as session:
    # Writes the graph, the schema registry and the node embeddings; commits the
    # graph connection itself, leaves the session commit to us.
    await service.upsert_knowledge_base(session, kb, "my_age_graph", model=embedding_model)
    await session.commit()

    # ...and the inverses: one knowledge base, or the whole graph plus its side-tables.
    await service.delete_knowledge_base(session, kb.id, "my_age_graph")
    await service.delete_graph(session, "my_age_graph")
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
- `tests/test_deep_agent.py` - test suite for `agent/deep_agent.py`'s `build_deep_agent()` factory
- `tests/test_chat_model.py` - test suite for `agent/chat_model.py`'s `Model` -> `ChatLiteLLM` mapping
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
- **deepagents** (>=0.7.13): Agent harness — `create_deep_agent()` supplies the filesystem,
  subagent, summarization and tool-call-patching middleware stack that `agent/deep_agent.py`
  assembles. Hard-depends on **langchain-anthropic** and **langchain-google-genai** (pure-Python; no
  credentials required when a model is always passed explicitly)
- **langchain-litellm** (>=0.7.1): `ChatLiteLLM`, the chat-model counterpart to the
  `litellm.aembedding()` call in `EmbeddingService` — built from a configured `Model` by
  `agent/chat_model.py`
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
  - `test_knowledge_base_can_write_nodes_and_relationships_to_age_graph()` - one
    `upsert_knowledge_base()` call writes the graph (recording fake repository) *and* both
    side-tables (real async SQLite session)
  - `test_delete_knowledge_base_removes_nodes_embeddings_and_registry_rows()` - round-trips
    upsert-then-delete: both nodes `DETACH DELETE`d, no `NodeEmbedding` rows, no registry rows left
  - `test_delete_knowledge_base_keeps_registry_rows_shared_with_another_base()` - deleting one of
    two knowledge bases sharing a label leaves the row with only the other's id, and leaves the
    other's node embeddings alone
  - `test_delete_graph_drops_the_graph_and_all_its_side_table_rows()` - rows for the dropped graph
    go, rows for another graph stay, and no per-node `DETACH DELETE` is issued
  - `test_delete_graph_cleans_side_tables_even_when_the_graph_is_already_gone()` - `graph_exists`
    False still clears the side-tables and returns `None`
  - `test_create_graph_creates_the_graph_and_is_a_no_op_when_it_exists()` - creates when absent,
    returns `None` and issues no query when present
  - `_RecordingAgeRepository` (in `tests/test_graph_registry_model.py`) - the shared fake for
    service-level tests: records the Cypher it's asked to run and its commit count, with a
    `graph_exists=False` switch for the does-not-exist paths
  - `test_age_graph_repository_get_node_neighbours_orients_source_target_via_edge_start_end_ids()` - regression test that source/target come from the edge's own `start_id`/`end_id`, not from assuming the queried node is always bound to the pattern's first variable
  - `test_age_graph_repository_get_node_neighbours_deduplicates_repeated_edge_rows()` - the same physical edge returned twice by a fake cursor still yields one triplet
  - `test_age_graph_repository_get_node_schema_queries_both_directions_by_id_property()` - asserts the outgoing `-[r]->` and incoming `<-[r]-` queries are both issued. Uses `_QueuedRowsConnection`, a fake that serves a *different* row batch per `execute` and records every query — `_RowsConnection` replays one fixed row set and so cannot represent a two-query method
  - `test_age_graph_repository_get_node_schema_orders_entries_deterministically()` - unordered fake rows still come back sorted per direction, outgoing before incoming
  - `test_get_properties_by_name_returns_properties_scoped_by_graph_and_type()` - a name shared by
    two `graph_name`s (or looked up under the wrong `type`) doesn't leak across the lookup; an empty
    `names` list short-circuits to `{}` with no query
  - `test_get_node_schema_returns_neighborhood_shape_grouped_under_the_node()` (`tests/test_tools.py`)
    - monkeypatches `GraphSchemaRegistry.get_properties_by_name` (keyed by the `type` argument) to
    assert the tool attaches the right property-name list to the node, to each relationship label,
    and to each neighbor label
  - `test_build_deep_agent_exposes_the_graph_tools()` / `..._adds_the_deepagents_and_todo_tools()` -
    compile the real graph against a `GenericFakeChatModel` (no network, no credentials) and read
    tool names off `agent.nodes["tools"].bound.tools_by_name`. Asserted as a **subset** on stable
    names only (`write_todos`, `task`, `ls`, `read_file`, `write_file`) — deepagents' full built-in
    tool set can change in a minor release
  - `test_build_deep_agent_passes_the_tools_prompt_middleware_and_context_schema()` - monkeypatches
    `deep_agent.create_deep_agent` and asserts the captured kwargs, pinning the wiring contract
    without coupling to deepagents' internal graph assembly
  - `test_build_chat_model_*()` - assert the `Model` -> `ChatLiteLLM` field mapping
    (`model`/`api_base`/`api_key`) and that `embedding_dimension` is *not* forwarded. Constructing a
    `ChatLiteLLM` performs no I/O, so these need no mocking at all
  - Not unit-testable here, by design: real provider calls, prompt quality / actual tool-call
    ordering (needs evals, not asserts), async streaming through `ChatLiteLLM`, and the four tools
    against live PostgreSQL+pgvector / Apache Age
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
