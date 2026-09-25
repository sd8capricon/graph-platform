# Agent Customization for graphrag-apacheage

> **Sync note:** This file and its counterpart must stay identical. Edit one, copy change to the other, same commit.
> **Keep current:** When you learn new patterns, conventions, or gotchas during work, add them to both files, same commit. Don't let docs drift from code.

## Project Overview

**graphrag-apacheage** is a Python library that bridges Microsoft's GraphRAG framework with Apache Age, a graph database extension for PostgreSQL. It provides data models, schema registry, and utilities for managing knowledge graphs in a relational database with graph capabilities.

**Stage**: Early development (0.1.0)  
**Python**: 3.14+ required  
**Build System**: uv (ultra-fast Python package installer)

### Projects (ADR-0004)

Three standalone uv projects under `src/`, each with its own `pyproject.toml`, `.venv` and
`uv.lock`. A service depends on `common` (a path dependency); `common` depends on no service, and
services do not import each other.

| Project | Import package | Owns |
|---|---|---|
| `src/common` | `common` | Configuration, domain schemas, shared ORM models, repositories, `EmbeddingService`, index DDL, the object storage abstraction (`storage/`), and the `api/` placeholder |
| `src/agent-runtime` | `agent_runtime` | Agent tools, prompt, `AgentContext`, serializers, and the deep/react agent assembly |
| `src/ingestion-worker` | `ingestion_worker` | The ingestion write path (idempotent graph `MERGE` + schema-registry/node-embedding upserts), the Celery app/tasks, the job dispatcher, and the legacy one-shot demo |

A module belongs in `common` only when at least two services need it, or it is a shared domain model
or the database schema itself (ADR-0004 Decision 4). `api` from the ADR's target four-service
topology has no project yet.

**Ingestion writes live in the worker.** The graph write, the `GraphSchemaRegistry` upsert, the
`NodeEmbedding` upsert and the `index_job`/`index_file` state store are ingestion-only, so they were
moved out of `common` into `ingestion_worker/` (ADR-0004 Decision 4). `common` keeps the shared
schemas, the ORM models' columns/relationships plus their **read** methods (`vector_search`,
`get_properties_by_name`), the `AgeGraphRepository`, `EmbeddingService` and index DDL.
`KnowledgeBaseService` in `common` is now lifecycle-only (`create_graph`/`delete_graph`/
`delete_knowledge_base`/`delete_graph_schema_registry`/`search_nodes`); the former
`upsert_knowledge_base`, `upsert_graph_schema_registry`, `upsert_node_embeddings`, the models'
`upsert_records`/`embedding_text` and the schema's extraction methods were removed and re-homed in
the worker (ADR-0005).

## Architecture

### Core Components

1. **Schemas** (`src/common/src/common/schemas/`)
   - `KnowledgeBase`: Container for nodes and relationships with JSON serialization
   - `KnowledgeNode`: Graph node with unique ID, label, and properties
   - `KnowledgeRelationship`: Graph edge connecting nodes with label and properties
   - Graph-payload schemas are input DTOs for ingestion; they are not ORM mappings. ORM-facing
     schemas are explicit Pydantic DTOs with `from_attributes=True`, kept in one schema module per
     model: `KnowledgeBaseRecordDTO`, `FileDTO`, `GraphSchemaRegistryDTO`,
     `NodeEmbeddingDTO`, and `SchemaEmbeddingDTO`. Persistence queries return DTOs, and ingestion extraction returns DTOs
     that the worker writer maps into ORM rows. `KnowledgeBaseRecordDTO` represents the API-owned
     resource row (`id`, organization/name/state/timestamps, serialized `data`, and `files: list[
     FileDTO]`, oldest first) and is distinct
     from the graph-payload `KnowledgeBase` above. `schemas/model.py`'s `Model` is provider config,
     not an ORM DTO; Python has no ModelConfig ORM mapping.
   - `Model` (`schemas/model.py`): Configured LLM/embedding provider connection (id, display_name,
     name, provider, connection_string, auth_mode, type capabilities, api_key, embedding_dimension,
     reasoning_effort) — validates that `api_key` is set when `auth_mode` is `api_key` and
     `embedding_dimension` is set when `embedding` is in `type`. `type` must be non-empty
     (`ensure_type_is_not_empty`) and `embedding` is exclusive of `vision`/`thinking`
     (`ensure_embedding_is_exclusive_of_chat_capabilities`) — an embedding model is a different
     litellm call shape (`aembedding()`) than a chat model, so one configured entry cannot be both.
     Passed into
     `EmbeddingService.compute_embeddings()` to describe which provider/model to call. `id` is a
     required, caller-assigned UUID (validated by `ensure_id_is_uuid`, not auto-generated) — it must
     stay stable across restarts because it is stamped as embedding provenance (`embedding_model_id`,
     see "Vector Embedding & Search Pattern" below) and is what `vector_search()` and the partial ANN
     index key off. This is distinct from `Model.identifier` (the `f"{provider}/{name}"` litellm
     model string), which is never used for provenance since two config entries can share one
     provider/name while differing
     in endpoint, auth mode, or dimension.
   - `Model.reasoning_effort` is optional and only meaningful for a non-embedding (chat) entry — a
     `@model_validator(mode="after")` (`ensure_reasoning_effort_not_for_embedding`) raises when it is
     set alongside `embedding` in `type`, the same "reject at the boundary" convention as
     `ensure_embedding_dimension_matches_type`'s inverse case (there, missing when required; here,
     present when forbidden). Consumed only by `agent_runtime/chat_model.py`'s `build_chat_model()` — see the
     "Agents" section below
   - Config entries name a secret indirectly via `api_key_env`; a `@model_validator(mode="before")`
     (`resolve_api_key_env`) pops it and reads that environment variable into `api_key`, so raw YAML
     entries validate straight into `Model`. There is no `Model.from_config()` — `AppSettings`
     (`config.py`) owns file reading, and the config file is parsed exactly once.

2. **Models** (`src/common/src/common/models/`)
   - `Base` (`models/base.py`): SQLAlchemy `DeclarativeBase` for Python-owned ORM tables
   - `ApiOwnedBase` (`models/base.py`): separate metadata for ORM mappings of tables whose DDL
     belongs to the management API; `create_all()` on `Base.metadata` does not include these
   - `KnowledgeBase` (`models/knowledge_base.py`): shared ORM mapping of the management API's
     `knowledge_base` resource table. It uses `ApiOwnedBase` metadata rather than `Base.metadata`,
      because EF owns the table's DDL and Python `create_all()` must not create it. Its PascalCase
      column names mirror the API migration; `job_store.py` uses this mapping for persistence and
      transfers the resource row as `KnowledgeBaseRecordDTO`. This is separate from
      `schemas.knowledge_base.KnowledgeBase`, the graph payload model. Its `files` relationship
      goes through the `knowledge_base_file` link table (`secondary=`), is one-directional, and uses
      `lazy="selectin"`, so `KnowledgeBaseRecordDTO.model_validate(row)` under an `AsyncSession`
      never lazy-loads (`MissingGreenlet`)
   - `File` (`models/file.py`): shared ORM mapping of the API-owned, **owner-agnostic** `file`
     table, also on `ApiOwnedBase` with PascalCase columns (`Id`, `OrganizationId`, `FileName`,
     `ContentType`, `Size`, `StorageKey` unique, `Status`, `CreatedAtUtc`, `UpdatedAtUtc`). One row
     per stored file; the content lives in object storage under `storage_key`, an ADR-0006 object
     key (never a path or URL). A file belongs to an organization, not to any particular resource:
     each owner links to its files through its own table, so a new owner (another model that needs
     files) adds a link table and never a column on `file`. Transferred as `FileDTO`
     (`schemas/file.py`, next to `FileStatus`: `uploaded` / `processing` / `processed` / `failed`,
     the API enum's snake_case values). The API is its only writer today. It is a true leaf with
     **no** relationships: a string-form back-reference fails `configure_mappers()` whenever the
     module is imported without its target, which `tests/test_file_model.py` checks in a fresh
     interpreter
   - `KnowledgeBaseFile` (`models/knowledge_base_file.py`): the Knowledge Base -> `File` link
     (`knowledge_base_file` table), a declarative class on `ApiOwnedBase` like every other model
     (`file_id` -> `FileId`, the primary key, so a file belongs to at most one knowledge base;
     `knowledge_base_id` -> `KnowledgeBaseId`; both FKs cascade). `KnowledgeBase.files` uses its
     `__table__` as `secondary`. It has no relationships of its own, so it stays a leaf
   - `GraphSchemaRegistry`: SQLAlchemy ORM model tracking node/relationship type definitions;
     `vector_search()` returns `GraphSchemaRegistryDTO`. `SchemaType` lives with that DTO in
     `schemas/graph_schema_registry.py` (the model module keeps a re-export for compatibility)
   - Stores: graph name, knowledge base IDs (list; a label may come from multiple knowledge bases), entity type, name, description, aliases, properties, source/target labels
   - Read methods: `vector_search()` (cosine-similarity search) and `get_properties_by_name()`. The upsert/merge write path is ingestion-only and lives in the worker as `ingestion_worker.ingestion.writer.upsert_schema_registry()`
   - `NodeEmbedding`: SQLAlchemy ORM model storing one vector embedding per knowledge base node;
     `vector_search()` returns `NodeEmbeddingDTO`
   - Stores: graph name, knowledge base ID, node ID, label, properties snapshot, embedding vector
   - Read methods: `vector_search()` - cosine-similarity search; plus `ensure_embedding_index()` / `drop_embedding_index()` DDL. The upsert write path lives in the worker as `ingestion_worker.ingestion.writer.upsert_node_embeddings()`
    - Both models share the pgvector embedding column pattern and delegate embedding computation
      to `EmbeddingService`; see "Vector Embedding & Search Pattern" below
   - `SchemaEmbedding`: SQLAlchemy ORM model holding the schema vector side table; represented in
     transfers by `SchemaEmbeddingDTO`, nested under `GraphSchemaRegistryDTO` where appropriate

3. **Agents** (`src/agent-runtime/src/agent_runtime/`)
   - `context.py` - `AgentContext`: pydantic model passed as `context_schema` to LangChain's
     `create_agent()`; holds run-scoped, static data (not conversational state), separate from
     graph state and made available to tools via LangGraph's runtime. Fields: `organization_id: str`
     (required — see ADR-0002, Decision 1; scopes every side-table read/write a run's tools perform
     to one organization), `graph_name: str`
     (required, the Apache Age graph the run's tools operate against), `attached_kb_ids: list[str]`
     (the knowledge base IDs a run's tools may operate against), `session: AsyncSession` (required
     — how tools reach the NodeEmbedding/GraphSchemaRegistry side-tables; needs `model_config =
     ConfigDict(arbitrary_types_allowed=True)` since `AsyncSession` isn't a pydantic type),
     `repository: AgeGraphRepository` (required — how tools reach the live Apache Age graph
     directly, e.g. for relationship traversal, as opposed to the `session`-backed side-tables),
     and `model: Model | None` (embedding provider for tools that vector-search; `None` means such
     tools should raise, matching `GraphSchemaRegistry.vector_search`'s own contract)
   - `models.py` - small tool-facing pydantic models that don't belong on `AgentContext` and aren't
     ORM/`schemas/` types either. Currently just `NodeRef` (`id: str | None = None`, `label: str`): a
     reference to a node that already exists in the graph, or to a whole label, used as
     `get_node_schema`'s `node` parameter instead of `schemas.knowledge_base.KnowledgeNode`.
     `KnowledgeNode.id` is optional and auto-generated by `KnowledgeNode.ensure_id()` when omitted —
     the right behavior for *authoring* a new node, but wrong for a *lookup* tool: an agent that
     omitted `id` would get back a fabricated UUID that matches nothing in the graph instead of the
     label-level answer it may actually have wanted. `NodeRef.id` is never generated — an omitted
     `id` stays `None` and is exactly the signal `get_node_schema` uses to switch to its label mode
     (see the `tools.py` bullet below), not a hole pydantic fills in. A *present but blank* `id`
     (`""`, `"   "`) is a different case — a malformed instance reference, not a request for label
     mode — and `get_node_schema` still rejects it (`node.id is not None and not node.id.strip()`) as
     defense in depth. `get_node_neighbours` still takes a `KnowledgeNode` (see below), which always
     requires a real `id` — promote it to `NodeRef` too if the same silent-fabricated-id failure mode
     is ever hit there (it has no label-mode use, so `id` would stay required)
   - `tools.py` - tool implementations. Tools access `AgentContext` by adding a
     `runtime: ToolRuntime[AgentContext]` parameter (imported from `langchain.tools`) and reading
     `runtime.context.*`; LangChain injects this argument automatically so it's excluded from the
     tool's schema shown to the model — don't document it in the tool's docstring or list it as a
     model-facing arg. `@tool`-decorated functions require a docstring (LangChain raises
     `ValueError` at decoration time otherwise), and can be `async def` when they need to await a
     model method. Both `search_schema_registry` and `search_entities` raise `ValueError` up front
     when `query.strip()` is empty, the same fail-fast convention `get_node_schema`/
     `get_node_neighbours` use for a missing/blank `node.id` — an empty query would otherwise reach
     `EmbeddingService.compute_embeddings()` and either waste a real embedding call on blank text or
     (with no `model` configured) silently return no results, instead of surfacing the bad input at
     the tool boundary. `search_schema_registry(query, runtime)` calls
     `GraphSchemaRegistry.vector_search(context.session, query, context.graph_name, context.model,
     knowledge_base_ids=context.attached_kb_ids)` and reshapes each result into a plain dict
     (type/name/description/aliases/properties/source_label/target_label) since tool return values
      must be JSON-serializable, not ORM instances; the model method already returns a DTO rather
      than an ORM row. `search_entities(query, runtime, labels=None)`
     calls `NodeEmbedding.vector_search(context.session, query, context.graph_name, context.model,
      labels=labels)` and reshapes each `NodeEmbeddingDTO` into a plain dict
      (node_id/label/properties) for the
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
     *overview* counterpart, in two modes selected by whether `node.id` is set. With `node.id`, it
     calls `await context.repository.get_node_schema(context.graph_name, node.id)` for that one
     instance; without it (label mode), `await context.repository.get_label_schema(context.graph_name,
     node.label)` for every node carrying that label. Both return the same
     `(relationship_label, direction, neighbor_label, count)` tuples, reshaped via
     `AgentSerializer.node_schema_to_dict()` into the distinct relationship label / direction /
     neighbor label combinations plus a `count` per combination — in label mode that `count` is a
     graph-wide total across every node of the label, not one node's degree. Use label mode to plan a
     traversal before holding a concrete node, and id mode before `get_node_neighbours` — both answer
     "what kinds of things does this connect to?" without returning every neighbor's full property
     dict. Neither mode takes a relationship-label filter on purpose: it's what the agent calls
     *before* it knows which labels matter, and every extra parameter enlarges the model-facing tool
     schema. `get_relationship(relationship, runtime, source_label=None,
     target_label=None, source_id=None, target_id=None, properties=None)` is the odd one out among the
     four other tools: it does not take a node reference (`NodeRef`/`KnowledgeNode`), since its whole
     point is finding relationships when the caller does **not** already hold one of the endpoints —
     `get_node_neighbours` covers the "I have a node, what's attached to it" case. It requires only a non-empty `relationship`
     label (raises `ValueError` on `relationship.strip()` being falsy, the same fail-fast convention as
     the other tools) and calls `await context.repository.search_relationships(context.graph_name,
     relationship, source_label=source_label, target_label=target_label, source_id=source_id,
     target_id=target_id, properties=properties)`, reshaping the returned `(source, relationship,
     target)` triplets via `AgentSerializer.relationship_matches_to_dict()`. Unlike
     `get_node_neighbours`'s single queried node, a relationship search can match many unrelated node
     pairs in one call, so there is no single node to group results under — each match is returned as
     its own `{"source", "relationship", "target"}` dict
   - `serializers.py` - `AgentSerializer`, a class of `@staticmethod`/`@classmethod` conversions
     (`schema_registry_record_to_dict()` / `node_embedding_record_to_dict()` /
     `node_neighbours_to_dict()` / `node_schema_to_dict()` / `relationship_matches_to_dict()`) shared by
     `tools.py`'s tool implementations. Search-record serializers take the matching Pydantic DTO,
     not an ORM instance. Grouped as one class purely for a single, discoverable import
     surface — none hold or need instance state. Kept in their own module, not prefixed with `_`, so
     they're importable/testable independent of any `@tool`-decorated function
   - `prompts.py` - `GRAPH_AGENT_SYSTEM_PROMPT`, the agent's system prompt. Its own module so
     replacing the prompt is a one-line change in one file: `deep_agent.py` imports the constant and
     never inlines prompt text, and `src/agent-runtime/tests/test_deep_agent.py` asserts prompt *identity*
     (`captured["system_prompt"] is GRAPH_AGENT_SYSTEM_PROMPT`), never prompt content, so swapping
     the text in cannot turn a test red. The shipped text is a deliberate **placeholder** — usable
     (it encodes the schema-discovery -> `search_entities` -> `get_node_schema` ->
     `get_node_neighbours` -> `get_relationship` call order the tools are designed around) but not
     the final prompt
   - `get_node_schema(node, runtime)` enriches its repository call's
     `(relationship_label, direction, neighbor_label, count)` tuples with property-**name** lists
     (not values) for the anchor label (`node.label`), each distinct relationship label, and each
     distinct neighbor label appearing in the entries — sourced from `GraphSchemaRegistry` via its
     `get_properties_by_name(session, graph_name, organization_id, names, type=None)` classmethod, not from the live
     Apache Age graph, since `GraphSchemaRegistry.properties` already **is** a property-name list
     (see "Schema Registry Pattern"); no new Cypher is needed and the already-fragile,
     unverified-against-a-live-instance `get_node_schema`/`get_label_schema` Cypher (see "Direct Graph
     Query & Async Repository Pattern") stays untouched. This enrichment is identical in both of the
     tool's modes — `[node.label]` names the anchor label whether or not `node.id` is also set — and
     is **not** sourced from `GraphSchemaRegistry` for the relationships/neighbour-label side of label
     mode instead: the registry stores only one `source_label`/`target_label` pair per relationship
     row (see "Schema Registry Pattern"), so
     it cannot represent a relationship used against several neighbour labels and carries no counts —
     only a live `MATCH (a:Label)-[r]->(b)` aggregation gives the real answer, which is exactly what
     `AgeGraphRepository.get_label_schema()` runs. The tool's `node` argument is a `NodeRef` (see
     `models.py` above), which has no `properties` field at all — the agent typically calls this tool
     precisely because it doesn't know the node's real property values yet, so there is nothing to
     read off the input for this. Three separate `get_properties_by_name` calls are made
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
     chat-completion meaning — and rejected on such a `Model` anyway by
     `ensure_reasoning_effort_not_for_embedding`'s embedding counterpart, see "Schemas" above), and
     nothing else is set by default, so provider defaults apply unless a caller passes `**overrides`
     (`temperature`, `max_tokens`, `profile`). `reasoning_effort`, when set, is forwarded via
     `model_kwargs={"reasoning_effort": ...}` rather than as a top-level `ChatLiteLLM` kwarg:
     `ChatLiteLLM`'s pydantic config is `extra="ignore"`, so an unrecognized top-level kwarg is
     silently dropped instead of reaching litellm's completion call, while `model_kwargs` is a
     declared field whose contents `ChatLiteLLM` spreads into that call. The `model` parameter is
     **positional-only** (`/`) because `model` is also `ChatLiteLLM`'s own field name — without the
     marker, `build_chat_model(cfg, model=...)` raises `TypeError: got multiple values for argument
     'model'` instead of overriding the model string. Note the deviation: the convention-consistent
     home for this is a shared `ChatModelService` mirroring `EmbeddingService`, since nothing about
     it is agent-specific. It lives in the `agent-runtime` project because it currently has exactly
     one caller; move it (file move + one import line in `deep_agent.py`) as soon as a non-agent
     caller appears
   - `deep_agent.py` - `build_deep_agent(chat_model, *, tools, middleware, system_prompt, name)`,
     the single place the agent is assembled. See "Deep Agent Assembly Pattern" below
   - `GRAPH_TOOLS` (in `tools.py`) - the ordered list of the five tools handed to the agent. It lives
     in `tools.py`, the module that owns the tools, **not** in `agent_runtime/__init__.py`: the
     package root is the service entrypoint (`main()`), so importing it to reach a tool list would
     drag the entrypoint's dependencies into every consumer. Import it as
     `from agent_runtime.tools import GRAPH_TOOLS`

4. **Services** (`src/common/src/common/services/`)
   - `KnowledgeBaseService`: Lifecycle-only service for knowledge base operations. Every method is
     `async def` (awaits the fully-async `AgeGraphRepository` and/or the awaited litellm embedding
     calls). It owns `create_graph`/`delete_graph`/`delete_knowledge_base`/
     `delete_graph_schema_registry`/`search_nodes` — see "Knowledge Base Lifecycle Pattern" below.
     The write path (`upsert_*`) was moved to the ingestion worker (ADR-0004 Decision 4)
   - `EmbeddingService` (`services/embedding_service.py`): Computes text embeddings via litellm,
     shared by any ORM model with a vector embedding column and by the worker's upserts

5. **Repositories** (`src/common/src/common/repositories/`)
   - `AgeGraphRepository`: Data access layer for Apache Age graph operations. Fully async, backed
     by `psycopg` v3's `AsyncConnection`/`AsyncCursor` (not `psycopg2`, which has no async mode).
     Most methods only build and `.execute()` a Cypher query, returning the query string itself
     (used as an audit trail) without
     fetching/parsing results — `graph_exists()` fetches but only checks `(await cursor.fetchone())
     is not None`. `get_node_neighbours()` and `get_node_schema()` are the methods that
     actually fetch and parse real result rows — see "Direct Graph Query & Async Repository
     Pattern" below. `merge_node()`/`merge_relationship()` are the idempotent (`MERGE`-on-`id`)
     write path the worker uses instead of `create_node()`/`create_relationship()`

6. **Database** (`src/common/src/common/database/`)
   - `indexes.py`: Model-agnostic DDL helpers for the per-model partial HNSW indexes on both
     embedding tables — `ensure_embedding_index()` / `drop_embedding_index()` plus
     `HNSW_MAX_DIMENSIONS`. It takes a `table_name` string rather than an ORM model, so it knows
     nothing about `NodeEmbedding`/`SchemaEmbedding`; both classes expose thin classmethods that
     pass their own `__tablename__` through. See "Vector Embedding & Search Pattern" below

7. **Storage** (`src/common/src/common/storage/`)
   - `base.py`: `StorageService` ABC, `ObjectMetadata`, the `StorageError` hierarchy and key/prefix/
     metadata validation. `filesystem.py` (`FileSystemStorage`) and `azure_blob.py`
     (`AzureBlobStorage`) are the providers, and `factory.py`'s `create_storage_service(settings)`
     picks one from `settings.storage` (`schemas/storage.py`). See "Object Storage Pattern" below

### Data Flow

```
JSON File → (worker) ingest_knowledge_base(
    session, repository, kb, graph_name, organization_id, model) → 3 writes in one call:
  1. nodes/relationships → ingestion_worker.ingestion.graph.merge_knowledge_base() →
     AgeGraphRepository.merge_node()/merge_relationship() (idempotent MERGE) → Apache Age graph
  2. ingestion_worker.ingestion.extraction.graph_schema_registry_records(...) →
     ingestion_worker.ingestion.writer.upsert_schema_registry()
     (embedding stored on the row's `embedding_row`, a SchemaEmbedding — see "Vector Embedding &
     Search Pattern")
  3. ingestion_worker.ingestion.extraction.node_embedding_records(...) →
     ingestion_worker.ingestion.writer.upsert_node_embeddings() (embeds via litellm)

KnowledgeBaseService.delete_knowledge_base(session, kb_id, graph_name, organization_id) →
the inverse (lifecycle stays in common):
  1. NodeEmbedding rows (organization_id, kb_id, graph_name) → node ids → repository.delete_node() (DETACH DELETE)
  2. DELETE those NodeEmbedding rows
  3. GraphSchemaRegistry: drop kb_id from knowledge_base_ids; delete rows left with none (their
     SchemaEmbedding child cascades via the ORM delete)

NodeEmbedding.vector_search(query, graph_name, organization_id) → nodes ranked by similarity
```

## Key Patterns & Conventions

### IDs and Identifiers
- **UUID generation**: Node, relationship, and knowledge base IDs are auto-generated as UUIDs if not provided
- Uses `@model_validator(mode="before")` in Pydantic models to ensure IDs exist
- See: `KnowledgeNode.ensure_id()`, `KnowledgeRelationship.ensure_related_ids()`, `KnowledgeBase.ensure_knowledge_base_id()`
- `ingestion_worker.ingestion.extraction.graph_schema_registry_records()` / `node_embedding_records()` raise `ValueError` when the knowledge base `id` is falsy. The id is auto-generated when the `id` key is absent from input, but an explicit `"id": null` survives `setdefault` and still raises

### Schema Registry Pattern
- One row per `(organization_id, graph_name, type, name)` — `organization_id` is part of the match key
  (see ADR-0002, Decision 1: every graph belongs to exactly one organization) so two organizations
  defining a schema under the same `graph_name` never collide; the same label (e.g. `Driver`) may
  still legitimately be defined by more than one knowledge base feeding the same graph *within* one
  organization, so the match key does **not** include the knowledge base id — instead the row is
  shared and accumulates every contributing knowledge base's id
- `ingestion_worker.ingestion.writer.upsert_schema_registry()` (moved out of the model as
  `GraphSchemaRegistry.upsert_records()`) performs smart merging:
  - Creates new records if not found
  - Merges aliases: `existing.aliases = sorted(set(existing.aliases) | set(record.aliases))`
  - Merges properties: `existing.properties = sorted(set(existing.properties) | set(record.properties))`
  - Merges knowledge_base_ids: `existing.knowledge_base_ids = sorted(set(existing.knowledge_base_ids) | set(record.knowledge_base_ids))`
  - Preserves source/target labels if not yet set
  - (Re)computes each persisted record's embedding via `EmbeddingService.compute_embeddings()`, but
    stores the vector on the record's `embedding_row` (a `SchemaEmbedding`, see "Vector Embedding &
    Search Pattern" below) rather than on `GraphSchemaRegistry` itself — reading/assigning
    `record.embedding_row` before the record is flushed is load-bearing, see that section
- `ingestion_worker.ingestion.extraction.graph_schema_registry_records(knowledge_base, graph_name, organization_id)` extracts schema records
  - Requires both `graph_name` and `organization_id` (neither stored on the model, both passed as
    arguments); stamps `organization_id` onto every constructed record
  - Requires `self.id` to be set (raises `ValueError` otherwise); sets `knowledge_base_ids=[self.id]` on each constructed record
  - Returns list of `GraphSchemaRegistry` records for nodes and relationships
  - Both node and relationship records always get `aliases=[]` — there is deliberately no alias
    source for either yet (a node's own `id` previously leaked into `aliases` by mistake, and
    relationship records were seeding `aliases` with `relationship.label`, which is redundant with
    `name`). Revisit once there's a real alias source (e.g. alternate display names)
- `GraphSchemaRegistry.get_properties_by_name(session, graph_name, organization_id, names, type=None)`
  looks up the stored `properties` list for a batch of names in one query (`name.in_(names)`, scoped
  by `organization_id` and `graph_name`, optionally filtered by `type`), returning a
  `dict[name, list[str]]` that omits any name with no matching row (rather than mapping it to `[]`) —
  the caller decides the default for a schema-less label. This is what `agent_runtime/tools.py`'s
  `get_node_schema` tool uses to attach property-**name** lists to its neighborhood summary (see the
  `agent_runtime/tools.py` bullet under "Agents" above); the same `type` value is shared across all `names`
  passed in one call, so a caller needing both node and relationship labels' properties makes two
  calls, not one
- See: `src/common/src/common/models/graph_schema_registry.py` and `src/common/src/common/schemas/knowledge_base.py`

### Knowledge Base Lifecycle Pattern
- `KnowledgeBaseService` owns the lifecycle of one knowledge base in one graph. It is now
  lifecycle-only — `create_graph`/`delete_graph`/`delete_knowledge_base`/
  `delete_graph_schema_registry`/`search_nodes` — because the ingestion write path moved to the
  worker (ADR-0004 Decision 4)
- The worker's `ingestion_worker.ingestion.pipeline.ingest_knowledge_base(session, repository,
  knowledge_base, graph_name, organization_id, model=None)` replaces the former
  `upsert_knowledge_base()`: it merges the graph
  (`ingestion_worker.ingestion.graph.merge_knowledge_base()` → `merge_node`/`merge_relationship` +
  `repository.commit()`), then `writer.upsert_schema_registry()`, then
  `writer.upsert_node_embeddings()`. It returns the list of executed Cypher queries (the graph
  audit trail). `organization_id` (see ADR-0002, Decision 1) is stamped onto every schema registry
  and node embedding row written, via the worker's extraction functions
  - Before either merge loop, it calls `repository.ensure_vertex_label()` once per distinct node
    label and `repository.ensure_edge_label()` once per distinct relationship label (deduplicated via
    `dict.fromkeys(...)`) — see the `ensure_vertex_label`/`ensure_edge_label` bullet under "Direct
    Graph Query & Async Repository Pattern" below for why: without it, a knowledge base with several
    nodes sharing a brand-new label (e.g. 27 `Driver`s) can raise
    `psycopg.errors.DuplicateTable: relation "Driver" already exists` from Apache Age's own racy
    implicit label auto-create, since all the merge calls here run in one transaction before the
    single `repository.commit()`
- `delete_knowledge_base(session, knowledge_base_id, graph_name, organization_id)` is the inverse and
  takes an **id**, not a `KnowledgeBase`: at delete time the source JSON is usually long gone. It
  gets the node ids to delete from the knowledge base's own `NodeEmbedding` rows (scoped to
  `organization_id`), which are the service's record of what it wrote to the graph — so a knowledge
  base written by something *other* than the worker's `ingest_knowledge_base()` (no `NodeEmbedding` rows) will not
  have its graph nodes removed
  - Nodes are removed with `repository.delete_node()`, i.e. `DETACH DELETE`, so relationships go
    with their nodes and no separate relationship pass is needed
  - Schema registry adjustment removes `knowledge_base_id` from each row's `knowledge_base_ids` and
    deletes only the rows left with no contributing knowledge base, since a label may be defined by
    several knowledge bases feeding one graph (see "Schema Registry Pattern")
  - **Known limitation:** a surviving shared row keeps the aliases and properties the deleted
    knowledge base contributed — the merge in `upsert_schema_registry()` is lossy and cannot be attributed
    back per knowledge base. Re-upsert the remaining knowledge bases if an exact schema is required
  - `delete_graph_schema_registry()` filters rows in **Python**, not SQL: `knowledge_base_ids` is a
    plain JSON column and a graph holds one registry row per label, so the scan is cheap and works
    on SQLite. Do *not* reach for the jsonb `?|` operator `GraphSchemaRegistry.vector_search()` uses
    — that's PostgreSQL-only and would make these paths untestable on SQLite
- `create_graph(graph_name)` / `delete_graph(session, graph_name, organization_id)` are the graph
  lifecycle pair. Both live on the service so callers never mix service and repository calls for the
  same concern, and both return `None` when there was nothing to do (graph already exists / graph
  already gone). `AgeGraphRepository` keeps its own raw `create_graph()`/`delete_graph()` pair — the
  service methods delegate to them; the asymmetry to avoid is a *layer* that owns one half of a pair
  - `create_graph()` takes no `session` on purpose: a new graph has no side-table rows, so there is
    nothing to create alongside it. Reusing a graph name dropped outside this service is the one gap
    — call `delete_graph()` first to clear any orphaned rows
- `delete_graph(session, graph_name, organization_id)` drops the Apache Age graph
  (cascading, so no per-node `DETACH DELETE` pass is needed) and then deletes **all**
  `NodeEmbedding` and `GraphSchemaRegistry` rows for that graph (scoped to `organization_id`).
  Registry rows are deleted outright rather than adjusted, unlike `delete_knowledge_base()` — the
  graph they describe is gone, so no contributing knowledge base has a remaining claim
  - The `SchemaEmbedding` rows belonging to those registry rows are deleted **first**, via their own
    bulk `delete()` statement (`SchemaEmbedding.graph_registry_id.in_(select(GraphSchemaRegistry.id)...)`).
    This method's `GraphSchemaRegistry` delete is a bulk `delete()`, which bypasses the ORM's
    `cascade="all, delete-orphan"` on `GraphSchemaRegistry.embedding_row` entirely — that cascade
    only fires for `session.delete()` on a loaded instance (which `delete_graph_schema_registry()`
    below uses), not for a bulk statement. Skipping this leaves orphaned `SchemaEmbedding` rows
  - A missing graph is deliberately **not** an error: dropping a graph is exactly what orphans the
    side-tables, so the rows are cleaned up either way. Returns the drop query, or `None` when the
    graph didn't exist and only the side-tables were cleaned
  - The side-table cleanup lives on the service and not on `AgeGraphRepository.delete_graph()` even though the
    repository's psycopg connection *could* run the `DELETE`s (same database) — and in one
    transaction with the drop, which this split does not get. **The original blocker is gone**: it
    was that naming the tables via `NodeEmbedding.__tablename__` would make
    `repositories/age_graph_repository.py` import the pgvector ORM models, which
    the old demo `__init__.py` imported at module level *before* `load_config()` — so the embedding
    column would have been sized from defaults. ADR-0003's dimensionless columns removed that constraint entirely. What remains is
    a weaker argument (an ORM-model import in the repository layer crosses a layer boundary this
    codebase otherwise keeps clean), so moving the cleanup — and gaining a shared transaction with
    the graph drop — is now a reasonable, deliberate follow-up rather than something ruled out
- Transaction split (all three methods): the **graph** connection is committed inside the method
  (`repository.commit()`), the SQLAlchemy `session` is only flushed — committing it is the caller's
  job, so a caller can batch several knowledge bases into one side-table transaction. The two stores
  are not in a shared transaction, so a failure between them can leave the graph ahead of the
  side-tables; re-running the upsert is idempotent and recovers
- See: `src/common/src/common/services/knowledge_base_service.py` and the
  `test_delete_knowledge_base_*` / `test_delete_graph_*` tests in `tests/test_graph_registry_model.py`

### Ingestion Pipeline Pattern (ADR-0005)
- RabbitMQ (broker) + Celery (task execution) + Postgres (`index_job`/`index_file` orchestration,
  the source of truth). No result backend (`task_ignore_result=True`) and no Redis; the pipeline
  never reads Celery return values. Fan-in is a guarded Postgres counter, **not** Celery chords
- `index_job`/`index_file` are API-owned DDL (EF migration), written by the Python worker through
  `ingestion_worker.job_store.IndexJobStore` using declarative ORM classes on private
  `IndexJobBase` (`ingestion_worker/models/base.py`), never on `common.models.base.Base.metadata` —
  so `create_all` never touches the API's tables. `IndexJob` and `IndexFile` live under
  `ingestion_worker/models/`, one class per model. The shared API-owned `knowledge_base` table mapping lives at
  `common.models.knowledge_base.KnowledgeBase` on `ApiOwnedBase.metadata`; the worker reads it as
  `KnowledgeBaseRecordDTO` and updates its lifecycle `State` through the same mapped model. That DTO
  carries the knowledge base's uploaded files (`files`, with each file's `storage_key`).
  **The inline `Data` graph-JSON column was removed** from the API, the DTO and the database (EF
  migration `RemoveKnowledgeBaseData`): a knowledge base's content is now only its uploaded files.
  Phase 1 ingestion read that column, so `jobs.ingest_job()` now raises a
  `NonRetryableIngestionError` naming the reason instead, and stays that way until file-based
  ingestion (Phase 2) is built.
  `create_job_tables(include_knowledge_base=True)` creates `knowledge_base`, `file` and
  `knowledge_base_file` stand-ins for tests
- Ingestion extraction returns `GraphSchemaRegistryDTO` / `NodeEmbeddingDTO` rather than transient
  ORM instances. `ingestion_worker.ingestion.writer` maps those DTOs into ORM rows for upsert and
  returns DTOs; no ORM objects cross the ingestion extraction/writer boundary
- The API never calls a worker: it writes a `queued` job row, and the Celery Beat **dispatcher**
  (`ingestion_worker/dispatcher.py`) claims it with `FOR UPDATE SKIP LOCKED` + a guarded
  `queued -> running` transition, commits, then publishes the task. Commit-before-publish means a
  crash leaves the job `running` for a future reconciler rather than losing it
- Worker modules: `models/` (`IndexJob`/`IndexFile` ORM classes) + `job_store.py` (`IndexJobStore`),
  `celery_app.py` (app + `ingestion` topic exchange, per-stage `q.<stage>`, `q.<stage>.retry` and
  `q.<stage>.dlq`; Phase 1 routes the combined task to `q.ontology`), `tasks.py`
  (`ingest_knowledge_base_task`; sync wrapper over `asyncio.run`, `autoretry_for` the retryable error,
  `on_failure` records the terminal failure), `jobs.py` (Celery-free `ingest_job`/`run_job`/`fail_job`),
  `errors.py` (retryable vs non-retryable classification: 429/5xx/timeout vs 4xx/parse), `db.py`,
  `config.py`
- Idempotency (required by `acks_late`): graph writes use `MERGE`-on-`id`
  (`AgeGraphRepository.merge_node`/`merge_relationship`), side-table writes are upserts, and the
  file row is reused via `IndexJobStore.find_file` on redelivery. A job already in a terminal state
  is skipped
- Phase 1 treats the whole knowledge base as one file and runs graph + embeddings in one task; the
  four-stage ontology/entity fan-out + guarded fan-in (`IndexJobStore.increment_and_check_fan_in`)
  and the files model are Phase 2

### Vector Embedding & Search Pattern
- **Schema-registry embeddings live in their own table, `SchemaEmbedding`** (`models/schema_embedding.py`,
  table `schema_embedding`), not inline on `GraphSchemaRegistry` — this is ADR-0002 Decision 5,
  implemented: `graph_registry` describes only schema (types, names, properties, aliases,
  source/target labels); the vector used for `vector_search()` similarity is a separate row, 1:1,
  keyed back via `graph_registry_id: Mapped[int] = mapped_column(ForeignKey("graph_registry.id",
  ondelete="CASCADE"), unique=True)`. `NodeEmbedding` (`models/node_embedding.py`) keeps its
  pre-existing separate-table split from the Apache Age graph itself — the two embeddings now share
  the same "own table, not inline" shape for different reasons (schema metadata vs. graph content)
  - `GraphSchemaRegistry.embedding_row: Mapped[SchemaEmbedding | None]` is the ORM relationship,
    `cascade="all, delete-orphan"`, `lazy="selectin"`, `uselist=False`. **Do not set
    `passive_deletes=True`** — with it, `await session.delete(parent)` leaves the child row behind
    on SQLite (no `PRAGMA foreign_keys=ON` in tests, so the DB-level `ON DELETE CASCADE` is
    Postgres-only belt-and-braces; the ORM cascade is what actually deletes the child in tests)
  - **Autoflush/lazy-load trap in `upsert_schema_registry()`:** for a brand-new record, `record.embedding_row = None`
    must be assigned *before* `session.add(record)` — the loop's next `select()` autoflushes the
    previous record to persistent state, and reading an *unloaded* relationship on a persistent
    object under `AsyncSession` raises `MissingGreenlet`. `lazy="selectin"` does not prevent this: it
    is a query-time loader and does nothing for a row that became persistent via autoflush. Only an
    explicit assignment marks the attribute loaded; reading it while pending does not
  - **Mutate the child in place, never replace it:** assigning a fresh `SchemaEmbedding` to a row
    that already has one raises `IntegrityError: UNIQUE constraint failed:
    schema_embedding.graph_registry_id`, because the unit of work orders INSERTs before DELETEs
    within a table, so the new child's insert races the pending delete-orphan of the old one
  - `vector_search()` reads the child via `.join(SchemaEmbedding, ...)` plus
    `.options(contains_eager(cls.embedding_row))` (folding the child into one SELECT instead of a
    second query the default `lazy="selectin"` would otherwise fire) and still returns
    `list[GraphSchemaRegistry]` — a 1:1 inner join cannot multiply rows, so no `.unique()` is needed
  - `delete_graph()` (`KnowledgeBaseService`) must delete `SchemaEmbedding` rows with their own bulk
    `delete()` statement, **before** the `GraphSchemaRegistry` delete — see "Knowledge Base Lifecycle
    Pattern" above. `delete_graph_schema_registry()` needs no such statement: it uses ORM
    `await session.delete(row)`, and the `cascade="all, delete-orphan"` relationship deletes the
    child automatically
- **Every row on both embedding tables is scoped by a required `organization_id`** (ADR-0002 Decision 1
  and its Open Questions recommendation): one shared table across all organizations, not a table per
  organization, with `organization_id` as an indexed, denormalized column rather than derived via a
  join. `GraphSchemaRegistry.organization_id` is part of its upsert match key
  (`organization_id, graph_name, type, name`) — see "Schema Registry Pattern" — and
  `SchemaEmbedding.organization_id` is the ADR's isolation filter on the embedding row itself;
  `vector_search()` asserts both agree (`cls.organization_id == organization_id` **and**
  `SchemaEmbedding.organization_id == organization_id`), so a mismatch (a bug) returns nothing rather
  than leaking across organizations. `NodeEmbedding.organization_id` is denormalized directly onto
  the row the same way `graph_name` already is (not derived via a join) and is part of its
  `UniqueConstraint("organization_id", "graph_name", "knowledge_base_id", "node_id")`
- **Row-level embedding-model provenance** (ADR-0001 option (1), rescoped by ADR-0002): both
  `SchemaEmbedding.embedding_model_id` and `NodeEmbedding.embedding_model_id` store the configured
  `Model.id` (not `Model.identifier` — a `provider/name` pair is not a stable identity for a
  configured model entry, since two entries can share one while differing in endpoint, auth mode, or
  dimension) that produced the row's vector, stamped by the worker upserts whenever an embedding is
  computed. There is deliberately no separate `embedding_model_id` filter parameter on either
  `vector_search()` — during the window between an organization admin changing the org's active
  embedding model and ADR-0002 Decision 4's mandatory recalculation finishing, a search is scoped to
  the passed-in `model` and so naturally sees only rows already migrated to it, rather than ranking
  old- and new-model embeddings together. Not implemented here: the recalculation job itself
- **Both embedding columns are dimensionless** — `Vector().with_variant(JSON, "sqlite")`, i.e. pgvector's `vector` type with *no* width (ADR-0003), so tests run against SQLite (embedding stored as JSON) while production uses PostgreSQL + pgvector. The width is deliberately not declared: a fixed one would be shared by every organization, which contradicts ADR-0002's "each organization picks its own embedding model" unless every model happens to emit the same number of dimensions. Neither model module imports `config` at all any more. Three consequences follow, and they are a matched set — changing one without the others silently breaks the others:
  - **The database no longer enforces vector width.** `EmbeddingService.compute_embeddings()` raises when a provider returns a vector whose length disagrees with `model.embedding_dimension`; it is the single choke point every vector passes through (both tables' upserts *and* both `vector_search()` query embeddings), and now the only thing preventing a mis-sized vector from being stored silently and failing much later at read time
  - **A dimensionless column cannot be ANN-indexed directly.** pgvector's documented workaround is an *expression* index casting to a fixed width, made *partial* so it only covers rows of that width — one per embedding model. See `database/indexes.py`'s `ensure_embedding_index()`, exposed as a classmethod on each embedding model. These are per *model*, not per organization, so the index count is bounded by how many providers the deployment supports rather than growing with tenant count. They cannot be static `__table_args__` entries (the model set isn't known at class-definition time) — which is also lucky, since an `Index(..., postgresql_using="hnsw")` there would be emitted by `create_all` against SQLite and break every test
  - **`vector_search()` must repeat both the predicate and the expression** or the index is not used: it always filters `embedding_model_id == model.id` and orders by `cast(embedding, Vector(model.embedding_dimension))`. Both are derived from the `model` argument rather than passed separately — see the `vector_search` bullet below
  - Models wider than **2000 dimensions** (pgvector's HNSW limit for `vector`, e.g. OpenAI `text-embedding-3-large` at 3072) still work but cannot be indexed this way; `ensure_embedding_index()` raises rather than emitting DDL PostgreSQL would reject
  - `AppSettings` (`config.py`) is a pydantic `BaseModel` holding all app config, and loads YAML in its constructor: `AppSettings(path)` reads the top-level `models:` list into `models: list[Model]`, so the config file is parsed exactly once at startup. `AppSettings()` (no path) touches no disk and uses field defaults. There is deliberately **no** process-wide `embedding_dimension`: `Model.embedding_dimension`, per provider entry, is the only dimension knob in the system
  - `config.load_config(path=DEFAULT_CONFIG_PATH)` updates the `settings` singleton's fields **in place** (it does not rebind the module-level name) so modules that already did `from common.config import settings` see the loaded values — rebinding would leave them holding a stale object. Each service entrypoint's `main()` is a call site (`agent_runtime/__init__.py`, `ingestion_worker/__init__.py`)
  - There is **no** `load_config()`-before-import ordering constraint any more. There used to be: the pgvector column width was fixed at class-definition time from `settings.embedding_dimension`, so importing a model module before `load_config()` silently baked in the default. Dimensionless columns (ADR-0003) removed the only thing read at class-definition time. The model imports in `ingestion_worker/__init__.py`'s `run()` still have to precede `create_all`, but only so the tables register on `Base.metadata` — not for ordering against config
  - The committed `configs/local.yaml` ships `models: []` with a filled-in template in comments. Placeholder/blank entries are deliberately NOT skipped — `auth_mode: ""` fails validation loudly, as does an `api_key_env` naming an unset variable, so misconfiguration surfaces at startup instead of silently yielding a keyless model
  - Import-cycle history: `models/graph_schema_registry.py` imports `services.embedding_service` and `services/knowledge_base_service.py` imports `schemas.knowledge_base`, but `schemas/knowledge_base.py` no longer imports back into `models.*` (its extraction methods moved to the worker), so the old cycle is gone. The empty-`__init__.py` discipline is still kept: `models/__init__.py`, `services/__init__.py`, and `repositories/__init__.py` are **intentionally empty** (docstring only, no re-exports), so importing one leaf module never runs its siblings as a side effect of `services/__init__.py` (or `models/__init__.py`) executing first. `schemas/`, `api/`, `database/`, and `storage/` have no `__init__.py` at all, for the same reason — and the service packages (`agent_runtime/`, `ingestion_worker/`) are outside `common` entirely, so their `__init__.py` files are entrypoints, not part of this cycle. Always import leaf modules directly (`from common.services.embedding_service import EmbeddingService`, never `from common.services import EmbeddingService`) and never add a re-export to one of these three `__init__.py` files — that's exactly what closes the loop again. `models/schema_embedding.py` is a true leaf: it imports only `models.base.Base`/`database.indexes`/`schemas.model`/sqlalchemy/pgvector, never `GraphSchemaRegistry` — the parent imports the child (`graph_schema_registry.py` imports `SchemaEmbedding`), and the child's back-reference (`Mapped["GraphSchemaRegistry"]`) uses the string form, resolved from the declarative registry rather than by evaluating the annotation, so importing it in the other direction is never needed. `database/indexes.py` is a leaf below both of them (`psycopg.sql`/`sqlalchemy.text`/`schemas.model` only), which is why both embedding models can import it. If you add a new cross-package module-level import, sanity-check it with `python -c "from common.<new_entry_point> import ..."` in a fresh interpreter — pytest's own import order can mask a real cycle
- Embeddings are computed by `EmbeddingService.compute_embeddings(model, texts)` (`services/embedding_service.py`) via `litellm.aembedding()` — both ORM models import `EmbeddingService` from there instead of defining their own copies
  - Takes an explicit `model: Model | None` (see `schemas/model.py`) describing the provider — builds the litellm model string as `model.identifier` (a `Model` property, `f"{provider}/{name}"`; also used by `agent_runtime/chat_model.py`'s `build_chat_model()`, so both read the same litellm model string the same way), passes `connection_string` as `api_base`, `api_key.get_secret_value()` as `api_key` when `auth_mode` is `api_key`, and `embedding_dimension` as `dimensions`. `model.identifier` is not used as embedding provenance — that is `model.id`, stamped by both worker upserts onto `embedding_model_id` (see above)
  - If `model` is `None` (or `texts` is empty), embedding is skipped entirely (returns `None`) so callers without a configured provider are unaffected — there is no global env var fallback
- The worker builds the embedded text via helpers (`schema_embedding_text` — name/description/aliases; `node_embedding_text` — label + `"key: value"` properties) and (re)computes it inside `upsert_schema_registry()` / `upsert_node_embeddings()` after merging/updating fields, by calling `EmbeddingService.compute_embeddings(model, texts)` — `upsert_schema_registry()` stores the result on `record.embedding_row` (see above), `upsert_node_embeddings()` stores it directly on the record
- `vector_search(session, query, graph_name, organization_id, model, ..., limit=5)` embeds the query text via the given `model`, then orders rows with pgvector's cosine distance operator — requires PostgreSQL, raises `ValueError` if `model` is `None` or has no `embedding_dimension`. Both checks happen **before** `compute_embeddings()`, since that is a real billed provider call and a model we cannot search against should never reach it
  - The search is always confined to rows `model` itself produced: it filters `embedding_model_id == model.id` and orders by `cast(embedding, Vector(model.embedding_dimension)).cosine_distance(...)`. There is deliberately **no** `embedding_model_id` parameter — both are derived from `model`, because both must agree with the query vector to mean anything (a cosine distance between two models' vectors is a meaningless number; between two *widths* it is an error), and because that pairing is exactly what makes the partial expression index matchable. A search therefore only ever sees rows embedded by the searching model — during an ADR-0002 recalculation window that is the desired behavior, not a limitation
- `NodeEmbedding` rows are keyed by `organization_id` + `graph_name` + `knowledge_base_id` + `node_id` (a `UniqueConstraint`), since the same `node_id` may legitimately be contributed by more than one knowledge base feeding the same graph — each combination is stored as its own row. `ingestion_worker.ingestion.extraction.node_embedding_records(knowledge_base, graph_name, organization_id)` builds one `NodeEmbeddingDTO` per node, requiring `knowledge_base.id` to be set (raises `ValueError` otherwise) and stamping `organization_id`/`knowledge_base_id` onto each DTO; `KnowledgeBaseService.search_nodes(session, query, graph_name, organization_id, model, ..., knowledge_base_id=None, ...)` wraps the search call and returns `NodeEmbeddingDTO` results. `NodeEmbedding.vector_search()` / `search_nodes()` take an optional `knowledge_base_id` (singular, equality filter) to scope a search to one knowledge base, and an optional `labels: list[str] | None` filtered via `cls.label.in_(labels)` (only applied when the list is non-empty) — plural because a caller (e.g. the `search_entities` agent tool) may want nodes matching any of several labels in one query, unlike the single-knowledge-base-at-a-time `knowledge_base_id` filter
- `GraphSchemaRegistry.vector_search()` takes an optional `knowledge_base_ids: list[str] | None` (plural, overlap filter) since a schema row's `knowledge_base_ids` is shared across contributing knowledge bases by design. Implemented as PostgreSQL-only: `cast(cls.knowledge_base_ids, JSONB).op("?|")(array(knowledge_base_ids))` — casts the plain-JSON column to `JSONB` at query time (no column-type change needed) and uses jsonb's `?|` "any of these strings present" operator; only applied when the list is non-empty, and covered by a compiled-SQL test the same way as the cosine-distance test (`FakeSession` capturing the statement, compiled against `postgresql.dialect()`) since neither `?|` nor `<=>` runs on SQLite
- Tests monkeypatch `embedding_service.litellm.aembedding` (import the module as `embedding_service`, not the individual ORM model modules) and pass a `Model` built via a small `_embedding_model()` test helper, to avoid real API calls
- See: `src/common/src/common/services/embedding_service.py`, `src/common/src/common/schemas/model.py`, `src/common/src/common/models/graph_schema_registry.py`, `src/common/src/common/models/schema_embedding.py`, `src/common/src/common/models/node_embedding.py`, and `tests/test_embedding_service.py` / `tests/test_schema_embedding_model.py` / `tests/test_node_embedding_model.py`

### Direct Graph Query & Async Repository Pattern
- `AgeGraphRepository` (`repositories/age_graph_repository.py`) is fully async, backed by `psycopg` v3's `AsyncConnection`/`AsyncCursor` — every method is `async def`. This replaced an earlier synchronous `psycopg2`-based repository, since `psycopg2` has no async mode at all; the worker's `ingest_knowledge_base()` is `async def` too, since it awaits repository calls internally
- Connection setup gotcha: every new Postgres session must run `SET search_path = ag_catalog, "$user", public;` before any `ag_catalog.*` call — AGE's internal DDL (e.g. the btree index it creates using its own `graphid_ops` operator class) resolves operator classes via `search_path`, not via schema-qualification of the calling query. Skipping this raises `psycopg.errors.UndefinedObject: operator class "graphid_ops" does not exist for access method "btree"` on `create_graph()`. `create_connection()` in `common/database/connection.py` runs `CREATE EXTENSION IF NOT EXISTS age;` (creates the `ag_catalog` schema/tables — `LOAD 'age'` alone only loads the shared library into the current session and leaves `ag_catalog.ag_graph` etc. undefined, raising `psycopg.errors.UndefinedTable` on `graph_exists()`) before `LOAD 'age';`, per Apache AGE's own documented setup order; on Azure-hosted Postgres (detectable via `"database.azure.com" in host`) the `age` extension's shared library is pre-loaded via server-side config, so `LOAD` is skipped, but `CREATE EXTENSION` still runs there too
- **Commit before handing off the connection:** `create_connection()`'s psycopg `AsyncConnection` defaults to non-autocommit, so its `CREATE EXTENSION`/`LOAD`/`SET search_path` setup statements sit in an open transaction until something commits. `ingestion_worker/__init__.py`'s `run()` opens a *separate* SQLAlchemy engine/connection right after and calls `Base.metadata.create_all` to create tables with `VECTOR` columns — under Postgres MVCC that connection can't see an uncommitted `CREATE EXTENSION vector`, raising `psycopg.errors.UndefinedObject: type "vector" does not exist`. `create_connection()` therefore ends with `await connection.commit()` before returning, so the extensions are visible to any other connection opened afterward
- Most methods only build and `.execute()` a Cypher query, returning the query string itself (used as an audit trail, e.g. by the worker's `ingest_knowledge_base()`) without fetching/parsing results — `graph_exists()` is the one exception that fetches, but only checks `(await cursor.fetchone()) is not None`
- `get_node_neighbours(graph_name, node_id, relationship_labels=None)` is the first method that actually fetches and parses real result rows: it matches a node via its app-level `id` property (the same property `create_node`/`create_relationship` set — not Apache Age's own internal vertex id/graphid), traverses relationships in both directions (`MATCH (a {"id": ...})-[r]-(b)`), and returns a de-duplicated `list[tuple[dict, dict, dict]]` of `(source, relationship, target)`
  - Apache Age returns each vertex/edge `agtype` column as a string suffixed with its Cypher type, e.g. `{"id": ..., "label": ..., "properties": {...}}::vertex` / `...::edge`. `_parse_agtype()` strips the `::vertex`/`::edge` suffix and `json.loads`es the remainder
  - De-duplicates on the edge's own internal `id` (not on a `(source, label, target)` tuple), since Apache Age can return the same physical edge twice for an undirected `()-[r]-()` pattern; a source/label/target-based key would incorrectly collapse legitimate parallel edges, since Apache Age is a multigraph
  - Source/target are oriented by comparing each vertex's internal `id` to the edge's `start_id`/`end_id`, since the queried node isn't always bound to the pattern's first variable (`a`)
- `_neighborhood_shape(graph_name, anchor)` returns the *shape* of a neighborhood rather than its
  contents: a `list[tuple[relationship_label, direction, neighbor_label, count]]`. It runs one query
  per direction — `MATCH (a<anchor>)-[r]->(b)` then `<-[r]-` — each `RETURN type(r), label(b),
  count(*)`, so direction comes from which query produced the row (no `start_id`/`end_id` comparison
  needed) and the *database* does the counting, meaning a high-degree anchor costs a handful of rows
  instead of one per relationship. Entries are sorted by `(relationship_label, neighbor_label)`
  within each direction, outgoing first, since the database guarantees no row order. A self-loop
  legitimately appears in both directions. It is a private helper with two public callers sharing an
  identical query shape but a different anchor fragment: `get_node_schema(graph_name, node_id)`
  anchors on one instance via `_age_properties_literal({"id": node_id})` (e.g. ` {id: 'driver-1'}`,
  `count` is that node's own degree per combination); `get_label_schema(graph_name, label)` anchors on
  every node carrying `label`, inlined bare as `:{label}` since a label has no literal form (`count`
  is a graph-wide total across all of them — 20 `Driver`s each with one `RACED_FOR` reports `20`, not
  `1`). Two public methods rather than one with an optional `node_id`: the modes have different
  required arguments, different `count` semantics, and different failure modes (bad id -> empty
  result; bad label -> injection risk)
  - The columns here are bare agtype *scalars*, not `::vertex`/`::edge` payloads. `_parse_agtype()`
    handles both (the suffix strip is a no-op for scalars), so its return type is `Any`, not `dict`
  - Unverified against a live Apache Age instance: `label(b)` and `count(*)` with implicit grouping,
    for both `get_node_schema` and `get_label_schema`. `type(r)` is already used by shipped code. Unit
    tests use fake cursors, so they pin the query string and the parsing, not that Age accepts the
    Cypher. If `label(b)` turns out to be unsupported on the target Age version, the fallback is to
    return `b` and read `b["label"]` in Python — which loses the DB-side aggregation and forces a
    client-side `count`
  - `_validate_label(label)` rejects anything that is not `str.isidentifier()` before it reaches
    `get_label_schema`'s Cypher. A label is inlined bare as `:{label}` — unlike ids and property
    values, which go through `_age_properties_literal()`'s quoting/escaping — so there is no literal
    form to make injection-safe by escaping; the label itself must be constrained instead.
    `create_node()`/`search_relationships()` inline labels the same unguarded way, but their labels
    come from validated `KnowledgeBase` data, not straight off an LLM tool call the way
    `get_label_schema()`'s does — adopting `_validate_label()` there too is a reasonable follow-up if
    that data source ever changes
- **`ensure_vertex_label(graph_name, label)` / `ensure_edge_label(graph_name, label)`** (both delegate
  to a shared private `_ensure_label(graph_name, label, create_function)`) exist because Apache Age's
  own implicit auto-create-on-first-`CREATE` for a brand-new label is racy across several `CREATE`
  statements for that label inside one still-open transaction — bulk-loading a `KnowledgeBase` with
  many same-label nodes (e.g. 27 `Driver`s) via `create_node()` in a loop with a single `commit()` at
  the end (see "Knowledge Base Lifecycle Pattern" below) reliably raised
  `psycopg.errors.DuplicateTable: relation "Driver" already exists` before this existed. Each method
  first checks `ag_catalog.ag_label` joined to `ag_catalog.ag_graph` on `graphid` for a row matching
  `(graph_name, label)`, and only calls `ag_catalog.create_vlabel`/`ag_catalog.create_elabel` when
  none is found — so it is safe to call every run, including against a graph whose labels already
  exist from a previous run. The worker's `merge_knowledge_base()` calls one of these once
  per **distinct** label (nodes' labels via `ensure_vertex_label`, relationships' labels via
  `ensure_edge_label`, each deduplicated with `dict.fromkeys(...)`) before its `create_node`/
  `create_relationship` loops — ensuring a label once, before anything `CREATE`s against it, sidesteps
  Age's auto-create race entirely rather than working around it after the fact
- `agent_runtime/tools.py`'s `get_node_neighbours` tool wraps this repository method and reshapes the triplets via `agent_runtime/serializers.py`'s `AgentSerializer.node_neighbours_to_dict(node_id, label, properties, triplets)`, which drops Apache Age's internal integer ids (keeping only the app-level UUID `id` pulled out of each vertex's `properties`) and groups results under the queried node once — `{"node": {...}, "relationships": [{"label", "properties", "direction", "neighbor"}, ...]}` — with `direction` ("outgoing"/"incoming") replacing a repeated source/target pair per entry, since a flat triplet-per-relationship list would echo the queried node's full dict once per relationship
- `search_relationships(graph_name, label, source_label=None, target_label=None, source_id=None, target_id=None, properties=None)` is `get_node_neighbours()`'s graph-wide counterpart: instead of traversing from one known node, it searches by relationship *type*, so `source_id`/`target_id` are optional constraints rather than the anchor of the match. It matches the single **directed** pattern `(a)-[r:label]->(b)` — the same orientation `create_relationship()` writes — so `source_label`/`source_id` always constrain the relationship's actual source and `target_label`/`target_id` its actual target; there is no undirected `-[r]-` traversal here, and therefore no `start_id`/`end_id` re-orientation or edge-id de-duplication like `get_node_neighbours()` needs. Endpoint labels are inlined as `:Label` on the pattern variable, endpoint ids and relationship `properties` are each rendered via `_age_properties_literal()`, and every filter is omitted (not just left empty) when its argument is `None`/falsy, so an all-`None` call degenerates to a plain `MATCH (a)-[r:label]->(b)`
- `agent_runtime/tools.py`'s `get_relationship` tool wraps this repository method and reshapes the triplets via `agent_runtime/serializers.py`'s `AgentSerializer.relationship_matches_to_dict(triplets)` into `[{"source": {...}, "relationship": {"label", "properties"}, "target": {...}}, ...]`. Unlike `node_neighbours_to_dict()`, there is no queried node to group under — a relationship search can legitimately match relationships between different node pairs in one call — so each triplet is reshaped independently rather than nested under a shared anchor
- No code in this repo yet constructs a real `psycopg.AsyncConnection` or wires a live `AgeGraphRepository` into `AgentContext` (`api/app.py` is empty) — this is a known, pre-existing gap; the async conversion makes `AgentContext`/`AgeGraphRepository` async-ready for whenever that wiring is added, it doesn't add the wiring itself
- See: `src/common/src/common/repositories/age_graph_repository.py`, `src/agent-runtime/src/agent_runtime/tools.py`, `src/agent-runtime/src/agent_runtime/serializers.py`, and the `test_age_graph_repository_get_node_neighbours_*` / `test_age_graph_repository_search_relationships_*` / `test_age_graph_repository_get_node_schema_*` / `test_age_graph_repository_get_label_schema_*` / `test_age_graph_repository_ensure_vertex_label_*` / `test_age_graph_repository_ensure_edge_label_*` tests in `tests/test_graph_registry_model.py`

### Deep Agent Assembly Pattern
- `agent_runtime/deep_agent.py`'s `build_deep_agent()` is the **only** place the agent graph is built. It
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
- See: `src/agent-runtime/src/agent_runtime/deep_agent.py`, `agent_runtime/chat_model.py`, `agent_runtime/prompts.py`,
  `agent_runtime/tools.py` (`GRAPH_TOOLS`), and `src/agent-runtime/tests/test_deep_agent.py` / `src/agent-runtime/tests/test_chat_model.py`

### Object Storage Pattern (ADR-0006)
- The design, the cross-stack contract (key rules, metadata rules, filesystem layout, sidecar
  schema) and its open questions are recorded in `docs/adr/0006-provider-agnostic-object-storage.md`.
  A change to any part of that contract must land in **both** stacks in the same change
- Business code depends only on `common.storage.base.StorageService`, never on the Azure SDK or on
  filesystem APIs. It receives the service through its constructor, the way `KnowledgeBaseService`
  receives its repository, and the entrypoint builds it once with
  `common.storage.factory.create_storage_service(settings.storage)`. The factory imports the providers
  lazily, so a filesystem deployment never loads the Azure SDK. Close the service with `aclose()` (or
  `async with`)
- **Object keys are the canonical reference.** Persist keys such as
  `documents/{documentId}/{fileId}/content.pdf`, never a filesystem path or blob URL.
  `ObjectMetadata` (`key`/`size`/`content_type`/`etag`/`last_modified`/`metadata`) never carries
  either. `validate_key()` runs before any provider sees a key and rejects: empty keys, keys over 1024
  characters, a leading or trailing `/`, `\`, control characters/NUL, `.`/`..` or empty segments, and
  drive prefixes. A list prefix follows the same rules but may end in `/`, and matches as a plain
  string prefix (`documents/do` matches `documents/doc-1/...`). User metadata must use ASCII-identifier
  names and ASCII values (Azure's rule, enforced for both providers), and names differing only by case
  are rejected
- API: `upload(key, bytes | AsyncIterable[bytes], *, content_type, metadata)`,
  `download(key, *, chunk_size)` (an async iterator of chunks), `read_bytes()`, `delete()` (idempotent,
  returns `False` when absent), `exists()`, `list(prefix)` (lexicographic), `get_metadata()`
- Errors: `download`/`read_bytes`/`get_metadata` on a missing key raise `StorageObjectNotFoundError`.
  Bad input raises `InvalidStorageKeyError`, which is both a `StorageError` and a `ValueError` (the
  codebase's bad-input convention). Azure SDK failures are wrapped in `StorageError` with
  `status_code` kept, so the worker's `classify_exception()` still sees 429/5xx. Wrapped messages hold
  only the operation, status and service error code, never request details
- `FileSystemStorage(root)` lays out `root/objects/<key>` (content), `root/meta/<key>` (a JSON sidecar
  with `content_type`, `metadata`, `etag`, `size`, `mtime_ns`) and `root/tmp/` (staging). The sidecar
  lives at `meta/<key>` with no `.json` suffix on purpose: a suffix would let keys `a` and `a.json/b`
  collide in the meta tree only.
  - **Writes:** stream to `tmp/` (all blocking I/O goes through `asyncio.to_thread`), `fsync`, then
    `os.replace` over the object, then write the sidecar the same way. Readers therefore never see a
    partial file, and a failed upload leaves the previous version. The rename is only atomic within
    one filesystem, so a Docker volume must be mounted at `root`, not `root/objects`.
  - **Reads:** a sidecar whose `size`/`mtime_ns` no longer match the file (a crash between the two
    replaces) is ignored, and metadata falls back to `stat`. `mtime_ns` is compared at 100 ns
    resolution because the .NET API's `FileSystemStorage` writes the same layout independently, using
    100 ns file-time ticks.
  - **Traversal defence:** besides key validation, any existing symlink component under `objects/` or
    `meta/` is rejected, as is a path that resolves outside the tree.
  - **Limitation:** a filesystem cannot hold both a file `a` and a directory `a`, so a key that is a
    `/`-prefix of another (`a` vs `a/b`) raises `StorageError`. Azure has no such restriction
- `AzureBlobStorage(settings)` uses `azure.storage.blob.aio`, with `aiohttp` as the async transport.
  - **Auth modes:** `auth_mode: connection_string` (development and Azurite) or `managed_identity`,
    which uses `azure.identity.aio.DefaultAzureCredential` with an optional
    `managed_identity_client_id` and needs `account_url`.
  - **Uploads:** `bytes` go through `upload_blob`. An async stream is buffered to `max_block_size` and
    written with `stage_block` + one `commit_block_list`, so memory stays bounded and a failed upload
    never becomes visible.
  - **Setup:** `create_container: true` creates the container lazily on first upload
- Config lives in the `storage:` section of `configs/local.yaml`, in `StorageSettings`
  (`schemas/storage.py`). The secret is never inlined: `connection_string_env` names an env var, and a
  `before` validator reads it into `connection_string: SecretStr`, mirroring
  `Model.resolve_api_key_env`. The env vars `STORAGE_PROVIDER` / `STORAGE_FILESYSTEM_ROOT` override
  the YAML, so containers can point at a volume. `azure_blob` credentials are checked (via
  `AzureBlobStorageSettings.ensure_credentials()`) only when it is the selected provider, so an
  Azure block can sit in the YAML with its env var unset. Both settings models set
  `hide_input_in_errors=True`, because pydantic otherwise echoes the raw input, including the resolved
  connection string, into `ValidationError` messages
- `common/storage/` has **no `__init__.py`** (same discipline as `schemas/`): import leaf modules
  (`from common.storage.base import StorageService`)
- Tests: `tests/test_storage_contract.py` is the provider contract. A parametrized fixture runs every
  case against `filesystem` (`tmp_path`) and `azure_blob`; `azure_blob` skips unless
  `AZURITE_CONNECTION_STRING` is set, and each test gets its own container. The contract covers:
  round trip, streams, overwrite, metadata, exists, delete, list, missing objects, invalid/traversal
  keys, and a 20 MiB streamed file with small blocks. `tests/test_filesystem_storage.py` covers the
  on-disk layout, symlink escape, failed-write atomicity, stale sidecars and pruning.
  `tests/test_storage_config.py` covers YAML/env resolution, secret redaction and the factory. To run
  the Azure cases, start Azurite (`docker run -p 10000:10000 mcr.microsoft.com/azure-storage/azurite
  azurite-blob --blobHost 0.0.0.0 --skipApiVersionCheck`, or `npx azurite-blob
  --skipApiVersionCheck`) and export `AZURITE_CONNECTION_STRING` as Azurite's documented default
  development-account connection string with `BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;`
- On the Python side nothing consumes storage yet. The API writes Knowledge Base file content
  through it (see "Files" under the API section), and the worker can read each file's
  `storage_key` off `KnowledgeBaseRecordDTO.files`. Reading that content during ingestion
  (ADR-0005 Phase 2) is follow-up work
- See: `src/common/src/common/storage/`, `src/common/src/common/schemas/storage.py`, and the three
  test modules above

### Validation & Constraints
- Type constraint in GraphSchemaRegistry: `type IN ('node', 'relationship')` via CheckConstraint
- Tests verify this constraint is enforced: `test_graph_registry_type_accepts_only_node_or_relationship()`
- `NodeEmbedding` has a `UniqueConstraint("organization_id", "graph_name", "knowledge_base_id", "node_id")` — one row per node per knowledge base per graph per organization
- `ingestion_worker.ingestion.extraction.graph_schema_registry_records()` / `node_embedding_records()` raise `ValueError` if the knowledge base `id` is falsy

## Common Tasks

### Adding a New Schema Type
1. Update `SchemaType` enum in `models/graph_schema_registry.py`
2. Add CheckConstraint to `GraphSchemaRegistry.__table_args__`
3. Add test in `tests/test_graph_registry_model.py`

### Loading and Registering a Knowledge Base
```python
from sqlalchemy.ext.asyncio import AsyncSession

from common.services.knowledge_base_service import KnowledgeBaseService
from ingestion_worker.pipeline import ingest_knowledge_base

kb = KnowledgeBase.from_json_file("path/to/kb.json")  # kb.id must be set

embedding_model = Model(
    id="550e8400-e29b-41d4-a716-446655440000",
    name="text-embedding-3-small",
    provider="openai",
    connection_string="https://api.openai.com/v1",
    auth_mode=AuthMode.API_KEY,
    api_key="...",
    type=[ModelType.EMBEDDING],
    embedding_dimension=1536,
)

# Graph lifecycle stays in common.
service = KnowledgeBaseService(repository)
await service.create_graph("my_age_graph")  # no-op if it already exists

organization_id = "org-1"  # see ADR-0002, Decision 1 - no Organization entity exists yet

async with AsyncSession(engine) as session:
    # The ingestion write lives in the worker: it merges the graph
    # (idempotent MERGE), then upserts the schema registry and node embeddings.
    # Commits the graph connection itself, leaves the session commit to us.
    await ingest_knowledge_base(
        session, repository, kb, "my_age_graph", organization_id, model=embedding_model
    )
    await session.commit()

    # ...and the inverses: one knowledge base, or the whole graph plus its side-tables.
    await service.delete_knowledge_base(session, kb.id, "my_age_graph", organization_id)
    await service.delete_graph(session, "my_age_graph", organization_id)
    await session.commit()
```

### Adding Vector Search for a New Entity
1. Subclass `Base` from `models/base.py` (don't redefine a new declarative base)
2. Decide inline vs. side table for the `embedding` column. If the entity's other columns are
   themselves a merge target (like `GraphSchemaRegistry`'s schema metadata), prefer a dedicated
   embedding table (see `models/schema_embedding.py`) so recalculation doesn't rewrite the
   entity's source-of-truth row — this is ADR-0002 Decision 5. Otherwise inline is fine (see
   `NodeEmbedding`)
3. Add a required, indexed `organization_id: Mapped[str]` column (ADR-0002 Decision 1/Open
   Questions: one shared table across organizations, not table-per-organization), a nullable
   `embedding_model_id: Mapped[str | None]` column (row-level provenance, holding the configured
   `Model.id` — not `Model.identifier` — per ADR-0001 option (1), *and* the predicate the partial
   index needs — see step 6), and the `embedding` column itself:
   `Vector().with_variant(JSON, "sqlite")` — dimensionless, per ADR-0003; do **not** declare a width,
   that would pin every organization to one embedding model size
4. Implement an embedding-text helper in `ingestion_worker/ingestion/writer.py`
   (`schema_embedding_text` / `node_embedding_text`) to build the text that gets embedded
5. Implement the upsert in `ingestion_worker/ingestion/writer.py` (the write path is ingestion-only,
   ADR-0004 Decision 4) and `vector_search(session, query, graph_name, organization_id, model, ...)`
   on the model, following the `NodeEmbedding` pattern (call
   `EmbeddingService.compute_embeddings(model, texts)` from `services/embedding_service.py` —
   don't duplicate the litellm call; stamp `record.embedding_model_id = model.id` alongside the
   vector). `organization_id` is always applied in `vector_search()`, not an optional filter — a row
   outside the caller's organization is never a valid match. If using a side table (step 2), see
   `upsert_schema_registry()`'s two documented traps: assign `record.embedding_row = None` before
   `session.add()` on a new record (autoflush + `MissingGreenlet` otherwise), and mutate an existing
   child in place rather than replacing it (`IntegrityError` otherwise)
6. In `vector_search()`, derive the model scope from the `model` argument — filter
   `embedding_model_id == model.id` and order by
   `cast(embedding, Vector(model.embedding_dimension)).cosine_distance(...)`. Don't add an
   `embedding_model_id` parameter; don't order on the uncast column. This is not stylistic: the cast and
   the predicate are what make the partial expression index usable, and dropping either silently
   falls back to a sequential scan (ADR-0003)
7. Expose `ensure_embedding_index(session, model)` as a classmethod delegating to
   `database/indexes.py`, so the table can be given its per-model ANN index
8. Add tests mirroring `tests/test_node_embedding_model.py` (round-trip on SQLite, skip-when-model-not-provided, litellm-mocked upsert with a `Model` built via a test helper, cosine-distance statement via a fake async session) plus an organization-isolation test (two organizations sharing the same natural key must not collide into one row), a provenance test (`embedding_model_id` gets stamped with `model.id`), and a `CreateTable`-compiled assertion that the column is `VECTOR` and not `VECTOR(n)` — SQLite never uses the pgvector type, so a declared width is invisible to every other test

### Testing New Features
- Use in-memory SQLite for fast tests: `create_engine("sqlite:///:memory:")`
- See: `tests/test_graph_registry_model.py` for patterns
- Run the `common` suite: `uv run --project src/common pytest tests/ -o asyncio_mode=auto`; run the
  agent suite: `uv run --project src/agent-runtime pytest`; run the worker suite:
  `uv run --project src/ingestion-worker pytest src/ingestion-worker/tests`

## Development Setup

### Required Tools
- Python 3.14+
- uv (package manager, configured in pyproject.toml)
- pytest (for testing)

### Key Files

The repository is three standalone uv projects plus shared top-level data, per ADR-0004:
`common` (shared library), `agent-runtime` (agent execution) and `ingestion-worker`
(knowledge-base ingestion). Each has its own `pyproject.toml`, `.venv` and `uv.lock`; imports of the
shared library resolve through a path dependency (`common` in `[project.dependencies]`, with
`[tool.uv.sources] common = { path = "../common", editable = true }` in each service).

- `src/common/pyproject.toml` - the `common` uv project: configuration, schemas, ORM models,
  repositories, the embedding service, index DDL and the `api/` placeholder. Standard uv layout, so
  the import package sits at `src/common/src/common/`
- `src/common/src/common/` - shared import package `common`
- `src/common/src/common/schemas/` - Pydantic DTOs paired with ORM models (one module per model),
  alongside the graph-payload schemas and provider configuration schema
- `src/common/src/common/database/connection.py` - `create_connection()` / `database_url()`: the
  Apache Age psycopg connection setup both services use
- `src/agent-runtime/pyproject.toml` - the `agent-runtime` uv project: agent dependencies,
  `uv_build`, the `agent-runtime` script entry point (`agent_runtime:main`), a `dev` group
  (pytest, pytest-asyncio) and `asyncio_mode = "auto"`
- `src/agent-runtime/src/agent_runtime/` - agent import package (`tools.py`, `prompts.py`,
  `deep_agent.py`, `react_agent.py`, `context.py`, `models.py`, `serializers.py`, `chat_model.py`)
- `src/ingestion-worker/pyproject.toml` - the `ingestion-worker` uv project: ingestion/Celery
  dependencies, `uv_build`, the `ingestion-worker` script entry point (`ingestion_worker:main`), a
  `dev` group (pytest, pytest-asyncio) and `asyncio_mode = "auto"`
- `src/ingestion-worker/src/ingestion_worker/` - ingestion import package (`celery_app.py`,
  `tasks.py`, `dispatcher.py`, `jobs.py`, `errors.py`, `db.py`, `config.py`, the `ingestion/`
  write path, and the legacy `run()`/`main()` demo)
- `src/ingestion-worker/src/ingestion_worker/models/` - declarative ORM classes for the API-owned
  `index_job`/`index_file` tables (one model per module, on a private `IndexJobBase`);
  the shared `knowledge_base` ORM mapping is `common.models.knowledge_base.KnowledgeBase`;
  `ingestion_worker/job_store.py` holds `IndexJobStore`
- `tests/test_graph_registry_model.py` - test suite (schema registry, general KnowledgeBase/service
  behavior, and `AgeGraphRepository` incl. `get_node_neighbours`)
- `tests/test_model_dtos.py` - verifies `from_attributes` conversions for DTOs paired with each ORM
  model (`KnowledgeBaseRecordDTO`, `GraphSchemaRegistryDTO`, `NodeEmbeddingDTO`, `SchemaEmbeddingDTO`)
- `src/ingestion-worker/tests/test_job_store.py` - test suite for `IndexJobStore` (guarded
  transitions, fan-in gate, KB read/state, `FOR UPDATE SKIP LOCKED` compiled SQL)
- `src/ingestion-worker/tests/test_models.py` - verifies class-based worker ORM mappings and
  private metadata ownership
- `tests/test_age_graph_repository_merge.py` - test suite for the idempotent `merge_node`/
  `merge_relationship` Cypher
- `src/ingestion-worker/tests/test_ingestion.py` - test suite for the worker's extraction, writer,
  graph-merge and `ingest_knowledge_base()` pipeline
- `src/ingestion-worker/tests/test_jobs.py` - test suite for `jobs.ingest_job()` (completion,
  idempotent redelivery, graph creation, classified failure)
- `src/ingestion-worker/tests/test_dispatcher.py` - test suite for the claim-then-publish dispatcher
- `src/ingestion-worker/tests/test_celery_app.py` / `test_errors.py` - Celery topology/config and
  retryable/non-retryable error classification
- `tests/test_schema_embedding_model.py` - test suite for `SchemaEmbedding` (the schema registry's embedding side table) and its cascade delete from `GraphSchemaRegistry`
- `tests/test_knowledge_base_model.py` - verifies the shared API-owned `KnowledgeBase` mapping and
  that it stays outside `Base.metadata`
- `tests/test_file_model.py` - verifies the owner-agnostic `File` mapping (column names, no FKs,
  `ApiOwnedBase` ownership), the `KnowledgeBaseFile` link mapping, that the `File` and `KnowledgeBaseFile`
  modules configure on their own in a fresh interpreter, `FileDTO`, and that `KnowledgeBaseRecordDTO` carries a
  knowledge base's files
- `tests/test_embedding_index.py` - test suite for `database/indexes.py`'s per-model partial HNSW index DDL
- `tests/test_node_embedding_model.py` - test suite for `NodeEmbedding` and node vector search
- `tests/test_embedding_service.py` - test suite for the shared `EmbeddingService`
- `tests/test_storage_contract.py` / `tests/test_filesystem_storage.py` / `tests/test_storage_config.py`
  - the storage provider contract (filesystem always, Azure on Azurite), filesystem-only behavior, and
  storage configuration/factory. See "Object Storage Pattern"
- `src/agent-runtime/tests/test_tools.py` - test suite for `agent_runtime/tools.py`'s `@tool`-decorated functions, run inside the `agent-runtime` project (`uv run --project src/agent-runtime pytest src/agent-runtime/tests`)
- `src/agent-runtime/tests/test_serializers.py` - test suite for `agent_runtime/serializers.py`'s dict-conversion helpers
- `src/agent-runtime/tests/test_deep_agent.py` - test suite for `agent_runtime/deep_agent.py`'s `build_deep_agent()` factory
- `src/agent-runtime/tests/test_chat_model.py` - test suite for `agent_runtime/chat_model.py`'s `Model` -> `ChatLiteLLM` mapping
- `tests/test_model.py` - test suite for `schemas/model.py`'s `Model` validators:
  `reasoning_effort`'s embedding-exclusivity rule; that `id` is required (not auto-generated - see
  the "Schemas" section above for why a stable id matters); and that `id` must be a valid UUID
- `dummy_data/f1_kb.json` - example knowledge base (Formula 1)
- `configs/local.yaml` - runtime config, read by `common.config.load_config()` relative to the
  working directory

### Running Tests

There is no `pyproject.toml` at the repository root, so `uv run pytest` from the root has no project
to resolve. Run each project's suite with its own environment:

```bash
# common: shared library tests (root-level tests/ directory)
uv run --project src/common pytest tests/ -o asyncio_mode=auto

# agent-runtime: agent tool/prompt/factory tests (src/agent-runtime/tests/)
uv run --project src/agent-runtime pytest src/agent-runtime/tests

# ingestion-worker: ingestion/Celery/dispatcher tests (src/ingestion-worker/tests/)
uv run --project src/ingestion-worker pytest src/ingestion-worker/tests
```

`asyncio_mode = "auto"` is configured in the `agent-runtime` and `ingestion-worker`
`pyproject.toml`s; for the root-level `common` suite it is passed with `-o` because pytest does not
discover a config file upward from `tests/`.

### Project Dependencies

`common` (everything shared):
- **pydantic** (>=2.13.5): Data validation and serialization
- **sqlalchemy[asyncio]** (>=2.0.42): ORM and database abstraction (async engine/session)
- **psycopg[binary]** (>=3.2): Async PostgreSQL/Apache Age connection (`AgeGraphRepository` is fully async via psycopg3's `AsyncConnection`/`AsyncCursor`)
- **pgvector** (>=0.5.0): `Vector` column type for embedding storage/cosine search
- **litellm** (>=1.99.0): Provider-agnostic embedding calls (`litellm.aembedding`); called only when a `Model` is passed to `EmbeddingService.compute_embeddings()`
- **pyyaml** (>=6.0.3): `AppSettings` config-file reading
- **azure-storage-blob** / **azure-identity** / **aiohttp**: `AzureBlobStorage`, i.e. the async blob
  client, `DefaultAzureCredential`, and the async HTTP transport both need. Imported lazily by
  `create_storage_service()`
- **fastapi[standard]** (>=0.141.1): reserved for the `common/api/` placeholder (the API service of
  ADR-0004 has no project of its own yet)
- Dev-only: **aiosqlite**, **pytest**, **pytest-asyncio** for the root-level `common` suite

`agent-runtime`:
- **common** (path `../common`, editable): shared schemas, models, repository and embedding service
- **deepagents** (>=0.7.13): Agent harness — `create_deep_agent()` supplies the filesystem,
  subagent, summarization and tool-call-patching middleware stack that `agent_runtime/deep_agent.py`
  assembles. Hard-depends on **langchain-anthropic** and **langchain-google-genai** (pure-Python; no
  credentials required when a model is always passed explicitly)
- **langchain** (>=1.4.0) / **langchain-litellm** (>=0.7.1): `create_agent()` and `ChatLiteLLM`, the
  chat-model counterpart to the `litellm.aembedding()` call in `EmbeddingService` — built from a
  configured `Model` by `agent_runtime/chat_model.py`
- **pydantic**, **sqlalchemy[asyncio]**, **python-dotenv**: `AgentContext`/`NodeRef`,
  `AsyncSession`, and `main()`'s `.env` loading
- Dev-only: **pytest**, **pytest-asyncio**

`ingestion-worker`:
- **common** (path `../common`, editable): the schemas, models, repository, `EmbeddingService`,
  lifecycle `KnowledgeBaseService` and the worker's own Core job-state store the ingestion path drives
- **celery** (>=5.5): the task execution/transport framework and RabbitMQ topology (kombu/amqp
  come transitively). Requires a running RabbitMQ broker (`RABBITMQ_URL`)
- **psycopg[binary]**, **sqlalchemy[asyncio]**, **python-dotenv**: the Age connection, the
  SQLAlchemy engine/session, and `main()`'s `.env` loading
- Dev-only: **aiosqlite**, **pytest**, **pytest-asyncio**

## Important Notes


### Testing Strategy
- Tests use SQLite in-memory databases (no PostgreSQL required for unit tests)
- Tests validate schema structure, constraints, and upsert logic
  - Ingestion-write tests (the upsert/extraction logic, `upsert_knowledge_base`) moved with the code
    into `src/ingestion-worker/tests/` (`test_ingestion.py`, `test_jobs.py`, `test_dispatcher.py`,
    `test_job_store.py`, `test_celery_app.py`, `test_errors.py`); the root `tests/` suite keeps the
    model/table/read/`vector_search`/repository/lifecycle coverage
  - `src/ingestion-worker/tests/test_job_store.py` - `IndexJobStore`: guarded transitions, fan-in
    gate, KB read/state, and the Postgres `FOR UPDATE SKIP LOCKED` compiled statement
  - `tests/test_age_graph_repository_merge.py` - the idempotent `merge_node`/`merge_relationship`
    Cypher
- Key tests:
  - `test_knowledge_base_parses_json_and_upserts_registry_rows()` - end-to-end JSON→DB flow
  - `test_graph_registry_type_accepts_only_node_or_relationship()` - constraint validation
  - `test_knowledge_base_graph_name_is_provided_to_service_not_stored()` - graph_name parameter pattern
  - `test_upsert_node_embeddings_computes_embedding_via_litellm_when_configured()` - monkeypatches `litellm.aembedding` (via `embedding_service.litellm`, shared by both embedding models) and passes a `Model` to avoid real API calls; also asserts `embedding_model_id` is stamped with `model.id`
  - `test_vector_search_embeds_query_and_builds_cosine_distance_statement()` - asserts on the compiled `postgresql` dialect SQL (via a fake async session) since pgvector's `<=>` operator can't run on SQLite; for `GraphSchemaRegistry` also asserts `JOIN schema_embedding` and both tables' `organization_id` columns appear
  - `test_vector_search_filters_by_multiple_labels_when_provided()` - asserts `NodeEmbedding.vector_search(..., labels=[...])` compiles to a `label IN (...)` filter (same fake-session/compiled-SQL approach)
  - `test_vector_search_scopes_to_the_query_model_without_being_asked()` - asserts that *without* passing anything, the compiled SQL carries both the `embedding_model_id` predicate and `CAST(... AS VECTOR(3))`; the pair is what keeps a search in one vector space and what the partial index needs (ADR-0003)
  - `test_node_embedding_column_is_dimensionless()` / `test_schema_embedding_column_is_dimensionless()` - compile `CreateTable` against the postgresql dialect and assert `VECTOR` with no width. Needed because SQLite falls back to `JSON` via `with_variant` and so cannot observe the width at all — every other test would pass with a wrongly-pinned column
  - `tests/test_embedding_index.py` - the partial/expression index DDL: exact statement shape, one index per model, hostile-model-id quoting, a UUID-length id staying within PostgreSQL's 63-byte identifier limit, and the `ValueError`s for a >2000-dimension model and a non-embedding model. Uses a `_RecordingSession` that captures DDL rather than running it, since these statements are PostgreSQL-only
  - `test_compute_embeddings_raises_when_provider_returns_wrong_width()` - the guardrail that replaced the column's own width enforcement (ADR-0003/ADR-0001 option 3)
  - `test_upsert_node_embeddings_keeps_separate_rows_per_knowledge_base()` - same `graph_name`/`node_id` from two different `knowledge_base_id`s upserts to 2 rows, not 1
  - `test_upsert_node_embeddings_keeps_separate_rows_per_organization()` / `test_upsert_records_keeps_separate_embedding_rows_per_organization()` (`tests/test_schema_embedding_model.py`) - two organizations sharing the same otherwise-identical natural key (graph_name/node_id, or graph_name/type/name) upsert to 2 rows, not 1 — `organization_id` is part of the identity, not just a filter
  - `test_upsert_records_merges_knowledge_base_ids_for_same_label_across_knowledge_bases()` - same label from two knowledge bases upserts to 1 shared row with both ids in `knowledge_base_ids`
  - `test_deleting_the_registry_row_cascades_to_its_embedding_row()` (`tests/test_schema_embedding_model.py`) - `session.delete()` on a `GraphSchemaRegistry` row deletes its `SchemaEmbedding` child via the ORM `cascade="all, delete-orphan"`, without relying on SQLite's (disabled-by-default) foreign key enforcement
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
  - `test_age_graph_repository_get_label_schema_queries_both_directions_by_label()` - the same two-query assertion as `get_node_schema`'s, but pinning `MATCH (a:Driver)-[r]->(b)` / `<-[r]-` (a bare label, not an `{id: ...}` property literal)
  - `test_age_graph_repository_get_label_schema_parses_scalars_and_tags_direction()` - counts come back as graph-wide totals (e.g. `20` across every `Driver`), not one instance's degree
  - `test_age_graph_repository_get_label_schema_rejects_unsafe_labels()` - parametrized over `["", "   ", "Driver) DETACH DELETE (a", "Driver-1", "1Driver"]`; asserts both the `ValueError` and that `connection.cursor_obj.queries == []` — no query is ever issued for a rejected label
  - `test_age_graph_repository_ensure_vertex_label_creates_when_missing()` / `..._skips_when_already_exists()` and the `..._ensure_edge_label_...` pair - a fake cursor queuing one `fetchone` result asserts `ensure_vertex_label`/`ensure_edge_label` issue an `ag_catalog.ag_label`/`ag_catalog.ag_graph` existence check first, and only call `create_vlabel`/`create_elabel` when that check comes back empty
  - `test_upsert_knowledge_base_ensures_labels_once_before_creating_nodes()` - the regression test for the `DuplicateTable` race: a knowledge base with two same-label nodes upserts to exactly one `create_vlabel` call (not two), positioned before either node's `CREATE`, and likewise one `create_elabel` call before the relationship's `CREATE`
  - `test_get_properties_by_name_returns_properties_scoped_by_graph_and_type()` - a name shared by
    two `graph_name`s (or looked up under the wrong `type`) doesn't leak across the lookup; an empty
    `names` list short-circuits to `{}` with no query
  - `test_get_node_schema_returns_neighborhood_shape_grouped_under_the_node()` (`src/agent-runtime/tests/test_tools.py`)
    - monkeypatches `GraphSchemaRegistry.get_properties_by_name` (keyed by the `type` argument) to
    assert the tool attaches the right property-name list to the node, to each relationship label,
    and to each neighbor label
  - `test_get_node_schema_returns_label_schema_when_id_is_omitted()` (`src/agent-runtime/tests/test_tools.py`) - a
    `NodeRef` with only `label` set calls `repository.get_label_schema()` (never `get_node_schema()`)
    and the result's `node` dict has no `node_id` key at all, not `node_id: None`
  - `test_get_node_schema_raises_on_empty_label()` (`src/agent-runtime/tests/test_tools.py`) - `label=""`/`"   "` raises
    before either repository method is called
  - `test_get_node_schema_raises_on_blank_id()` (`src/agent-runtime/tests/test_tools.py`, renamed from
    `test_get_node_schema_raises_on_empty_id`) - a `NodeRef` built with `""` or `"   "` as `id` still
    raises rather than silently falling back to label mode; only an *omitted* `id` selects that mode
  - `test_node_ref_id_is_optional_but_never_generated()` (`src/agent-runtime/tests/test_tools.py`, renamed from
    `test_node_ref_requires_id`) - `NodeRef(label=...)` with no `id` now constructs fine with
    `id is None`, in contrast to `KnowledgeNode(label=...).id`, which is still auto-generated
  - `test_age_graph_repository_search_relationships_matches_directed_pattern_by_label()` /
    `..._filters_by_endpoint_labels_and_ids()` / `..._filters_by_relationship_properties()` - assert
    the directed `(a)-[r:label]->(b)` pattern and that each optional filter (endpoint label, endpoint
    id, relationship property) is inlined only when provided
  - `test_get_relationship_reshapes_matches_via_serializer()` (`src/agent-runtime/tests/test_tools.py`) - asserts the
    tool passes every filter argument through to `AgeGraphRepository.search_relationships()` by
    keyword and reshapes the returned triplets via `AgentSerializer.relationship_matches_to_dict()`
  - `test_get_relationship_raises_on_empty_relationship_label()` - same fail-fast convention as
    `search_schema_registry`/`search_entities`'s empty-query check, for the relationship label instead
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

## API (`src/api`, .NET)

`src/api` is an ASP.NET Core (net10.0) management API — the `api` service of ADR-0004 — and the first
writer of the Organization/User/Model/Knowledge Base tables ADR-0002 Decisions 1–3 call for. It is *not* a Python
project: no `pyproject.toml`, no `common` import. `GraphPlatform.slnx` holds two projects:
`GraphPlatform.Api` (production code) and `GraphPlatform.Api.Tests`.

### Layout and conventions
- One production project, folder-based layering: `Controllers/`, `Dtos/`, `Data/`, `Models/`,
  `Services/`, `Extensions/`. All DTOs share the single namespace `GraphPlatform.Api.Dtos` even though
  the files sit in `Dtos/Auth`, `Dtos/Organizations`, `Dtos/ModelConfigs`, `Dtos/KnowledgeBases` — a `Dtos.Models` namespace
  would make `Models.AuthMode` resolve to the DTO namespace instead of `GraphPlatform.Api.Models`.
- `Models/` holds EF Core entities, the C# counterpart of Python's `models/`; `Data/AppDbContext.cs`
  maps them and `Data/Migrations/` holds the EF migrations.
- DTOs are hand-mapped in `Dtos/DtoMappings.cs` (`ToDto()` extensions) — no mapping library, because a
  convention-based mapper is exactly how `ModelConfig.ApiKey` would leak onto a response. `ModelDto`
  exposes only `HasApiKey`.
- Validation mirrors `common/schemas/model.py`, with one deliberate divergence: this API has no
  `authMode` field on `ModelWriteRequest` at all — it only ever authenticates with an API key, so
  `apiKey` is unconditionally required rather than conditioned on `auth_mode` the way Python's
  `Model.auth_mode` still allows (`managed_identity` stays valid for YAML-configured Python entries,
  which this admin API does not manage). `ModelConfig.AuthMode` stays on the entity/`ModelDto` as a
  read-only, always-`api_key` value, so the column and the shared `model_config` table shape are
  unchanged. `IValidatableObject` on `ModelWriteRequest` otherwise enforces: `type` must be
  non-empty; `embedding ∈ type` is exclusive of `vision`/`thinking` ∈ `type` (an embedding model
  cannot also be a chat model); and `embedding ∈ type` ⇒ `embeddingDimension` required and
  `reasoningEffort` forbidden. `[ApiController]` turns failures into 400 `ValidationProblemDetails`.

### Shared-database contract with the Python services
- One PostgreSQL database, two owners: Python's `Base.metadata.create_all` creates
  `graph_registry`/`node_embedding`/`schema_embedding`; EF creates `organization`, `user_organization`,
  `model_config`, `knowledge_base`, `file`, `knowledge_base_file` and Identity's `AspNet*` tables. `AppDbContext` deliberately knows nothing about the
  Python tables, and the migration only ever creates tables.
- **`organization_id` is a string (`varchar(255)`), never a `Guid`.** Python stores it as
  `String(255)` and the shipped entrypoints hardcode `DEMO_ORGANIZATION_ID = "demo-org"`, so a `uuid`
  key could not represent those rows. `ModelConfig.Id` is a string for the same reason (Python
  documents `Model.id` as "stored as `str`, not `UUID`") while still being validated to parse as a UUID.
- Enum values are persisted *and* serialized the way Python spells them — lower snake-case (`api_key`,
  `managed_identity`, `embedding`, `organization_admin`, …). One helper does both: `Data/Converters.cs`'s
  `SnakeCaseEnum<T>()` plus a global
  `JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower, allowIntegerValues: false)` in
  `Program.cs`. A plain `HasConversion<string>()` would silently persist `ApiKey`.
- `ModelConfig.Type` is a `jsonb` column holding a JSON array, via a string value converter; Npgsql
  documents a `string` property with `HasColumnType("jsonb")` as a supported mapping.
- `KnowledgeBase` (`Models/KnowledgeBase.cs`) stores the resource `Id`/`Name`, its organization, UTC
  timestamps and `KnowledgeBaseState`. It carries **no graph payload**: the former `Data` (`jsonb`)
  column, the `id`/`name` overlay onto that payload, and the node/relationship shape validation in
  `KnowledgeBaseWriteRequest` were all removed, so a write request is just a `Name` (plus an optional
  caller-assigned `Id` on create). Content comes from the files uploaded through
  `KnowledgeBaseFilesController`. Member reads are organization-scoped;
  Contributor/Admin mutations create drafts, and update/delete are draft-only. Publish changes a
  draft to `indexing`; the ingestion worker and dispatch/completion bridge are not wired to this API,
  so completion to `published` remains future integration work.
- ADR-0002 roles are **per organization**, so they live in `user_organization.Role`, not in ASP.NET
  Identity roles: `AppDbContext` derives from `IdentityUserContext<AppUser>`, not
  `IdentityDbContext<AppUser>`, so `IdentityRole`/`IdentityUserRole`/`IdentityRoleClaim` are never
  mapped in the first place — the earlier `IdentityDbContext` base plus `builder.Ignore<IdentityRole>()`
  etc. logged "first mapped explicitly and then ignored" warnings, since the base class's own
  `OnModelCreating` maps them before an `Ignore` call can remove them. This is safe because
  `AddIdentityCore` without `AddRoles` registers no role store. The JWT carries identity only (`sub`,
  `email`, `jti`, `iat`, `exp`); the role is re-read from the membership table per request, so a role
  change takes effect immediately instead of when the token expires.
- Migrations are never applied automatically (`Database:AutoMigrate` is false even in
  `appsettings.Development.json`) because the API shares its database with the Python services.
  Apply them deliberately: `dotnet ef database update --project GraphPlatform.Api`.
- Connection string resolution is a direct read of `ConnectionStrings:PgConnectionString` — no
  factory, no fallback chain (the old `Data/ConnectionStringFactory.cs`, its `ConnectionStrings:Default`
  fallback and its `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD` fallback are gone). The key name is the
  constant `AppDbContext.ConnectionStringName`, read by both `Program.cs` and
  `Data/AppDbContextFactory.cs` so the two cannot drift. **Removing the factory also removed the only
  validation of this key:** `UseNpgsql` accepts an empty string or a null (verified with the committed
  empty stub, and with the key deleted, via `dotnet ef dbcontext info` — both yield an empty
  `Database name`/`Data source` and no error), so Npgsql's own defaults (`localhost`, current OS user)
  apply instead of a startup failure. A missing key is therefore a silent misconfiguration that
  surfaces later as a connection error, not a fail-fast.
- Secrets — the development connection string and the JWT signing key — live in
  `appsettings.Development.json`, which is **gitignored**; the committed `appsettings.json` carries
  empty stubs for `ConnectionStrings:PgConnectionString` and `Jwt:SigningKey` so the keys stay
  discoverable without a value ever being committed. The API no longer loads the repository-root
  `.env`: `Data/DotEnvLoader.cs` and the `DotNetEnv` package are gone. The Development connection
  string was copied from that `.env` into the gitignored file, so the API and the Python services
  reach the same database, and the two copies must be kept in step by hand. A fresh clone therefore
  has no usable Development configuration — create `appsettings.Development.json`, or set
  `ConnectionStrings__PgConnectionString`/`Jwt__SigningKey`, before starting the API. Tests are
  unaffected: `GraphPlatformApiFactory` sets `Jwt__*` and swaps the context to SQLite.

### Authorization conventions
Resolved by `Services/OrganizationAccessService.cs`. A non-member gets **404**, not 403, so the API
never confirms that an organization the caller cannot see exists; a member lacking the role gets 403.
Any authenticated user may `POST /api/organizations` (the bootstrap path — the creator becomes its
first Organization Admin). Creating a model needs Contributor or Admin; choosing the org's active
embedding model needs Admin (ADR-0002, Decision 3). The last Organization Admin cannot be demoted or
removed (409), and the active embedding model cannot be deleted (409). Knowledge Base reads are
available to any member; create/update/delete/publish require Contributor or Admin, with update and
delete additionally restricted to drafts. Knowledge Base files follow the same rules: any member may
list, read or download them, and upload/delete need Contributor or Admin and a draft Knowledge Base.

### Files
- `Models/File.cs` (`file` table) is **owner-agnostic**: metadata (`FileName`, `ContentType`, `Size`,
  `Status`, timestamps), `OrganizationId` (FK -> `organization`, cascade) and the `StorageKey`, with
  no owner column.
  - Owners link to files through their own table. Today that is only `Models/KnowledgeBaseFile.cs`
    (`knowledge_base_file`: `FileId` PK, `KnowledgeBaseId`, both FKs cascade), mapped as the join
    entity of the unidirectional many-to-many `KnowledgeBase.Files` (`HasMany().WithMany()
    .UsingEntity<KnowledgeBaseFile>`).
  - To give another model files, add a link entity and table the same way and reuse
    `FileService`. Do not add an owner column to `file`.
  - The migration is `AddFiles`.
- **The name collides with `System.IO.File`**, which implicit usings import everywhere. Files that
  need the entity declare `using File = GraphPlatform.Api.Models.File;`.
  - Never make that alias global: the storage providers and their tests call `System.IO.File`.
  - Inside a controller, `File(...)` still binds to `ControllerBase.File` (class members beat
    aliases), but so does `File.Member`, so write `Models.File.FileNameMaxLength` there.
- `Services/FileService.cs` (scoped) owns storage/row consistency, since storage and the database
  share no transaction:
  - `CreateAsync(organizationId, fileName, contentType, stream, attach, ct)` uploads the object
    first, adds the `File` row plus whatever `attach` links to the owner, and saves once. If the
    save fails, it makes a best-effort delete of the object (with `CancellationToken.None`) and
    rethrows.
  - `RemoveAsync(files, ct)` deletes the objects **first**, then marks the rows removed. The
    caller saves, so it can batch the removal with the owner's own changes. A storage failure
    leaves every row in place for a retry (storage deletes are idempotent); the reverse order would
    strand objects no row refers to.
  - Every path that deletes an owner calls it, because database cascades cannot reach storage:
    `KnowledgeBasesController.DeleteKnowledgeBase` and `OrganizationsController.DeleteOrganization`.
  - `SanitizeFileName` keeps only the last `/`- or `\`-separated segment and rejects control
    characters. `NormalizeContentType` falls back to `application/octet-stream`.
- Storage key: `File.BuildStorageKey()` builds `organizations/{orgId}/files/{fileId}/content`.
  - Neither the owner nor the uploader's file name is part of it, so a key never depends on a
    caller-assigned id or name.
  - `StorageKey` is not on `FileDto`, since clients download through the API.
- `Controllers/KnowledgeBaseFilesController.cs`, at
  `api/organizations/{organizationId}/knowledge-bases/{knowledgeBaseId}/files`:
  - `POST`: multipart, `file` part, returns 201 with `FileDto`.
  - `GET` lists the files; `GET {fileId}` returns one file's metadata.
  - `GET {fileId}/content` streams the content.
  - `DELETE {fileId}` returns 204.
  - Files are looked up through the link row, so a file id is only reachable under its own
    Knowledge Base and organization.
  - `KnowledgeBaseDto.Files` lists the same DTOs, oldest first.
- Size limit: `FileUploads:MaxFileSizeBytes` (`Services/FileUploadOptions.cs`), default 100 MiB,
  validated on start. An oversized file gets 413, and an empty file or a missing `file` part gets
  400.
  - Upload endpoints apply `[TypeFilter<FileUploadLimitsFilter>]`, a resource filter that raises
    Kestrel's body limit and the multipart limit before model binding reads the form.
  - `[RequestSizeLimit]`/`[RequestFormLimits]` cannot do this, because they need compile-time
    constants.
  - There is no content-type allow-list.
- Tests: `GraphPlatform.Api.Tests/KnowledgeBaseFileEndpointTests.cs` covers:
  - storage, row and link consistency, download and file-name sanitising;
  - Knowledge Base and organization delete cleanup;
  - the draft-only and role rules, and cross-organization 404s;
  - the size limit (`WithWebHostBuilder` configuration);
  - a storage outage during delete, using a `ConfigureTestServices` decorator whose `DeleteAsync`
    throws, which must leave the row for a retry.
  - Not covered: the orphan cleanup when `SaveChangesAsync` fails after an upload

### Storage (ADR-0006)
- `Services/Storage/` holds `IStorageService` (the API's first interface), `FileSystemStorage`,
  `AzureBlobStorage`, `StorageKey` (key/prefix/metadata validation), `StorageObjectMetadata` /
  `StorageUploadOptions` / `StorageDownload`, the exception types (`StorageException` with
  `StatusCode`, `StorageObjectNotFoundException`, and `InvalidStorageKeyException : ArgumentException`)
  and `StorageOptions`. It is implemented independently of Python's `common.storage`, with no shared
  code, but follows the same documented contract (key rules, metadata rules, and the
  `objects/`/`meta/`/`tmp/` on-disk layout with snake-case sidecars), so both stacks could share a
  volume
- `Extensions/StorageServiceCollectionExtensions.cs`'s `AddStorage(configuration)`, called from
  `Program.cs`, uses the options pipeline (`AddOptions().Bind().PostConfigure().ValidateOnStart()`
  plus `StorageOptionsValidator`). This deliberately departs from `JwtOptions`' eager `Get<T>()`: the
  lazy bind lets `GraphPlatformApiFactory` override `Storage:*` through `AddInMemoryCollection`
  without the env-var workaround JWT needs. The selected provider is a singleton `IStorageService`. A
  relative `Storage:FileSystem:Root` resolves against the content root. The default is
  `App_Data/storage`, not `data/storage`, because on macOS's case-insensitive filesystem `data/` *is*
  the EF `Data/` folder (and `.gitignore` anchors `/data/` for the same reason under
  `core.ignorecase`)
- `STORAGE_PROVIDER` (`filesystem`/`azure_blob`) and `STORAGE_FILESYSTEM_ROOT` are honoured through a
  `PostConfigure`, the same variables Python reads. `Storage__*` works too. The connection string is
  a secret: its `appsettings.json` stub is empty, validation messages name the key without echoing
  the value, and `AzureBlobStorageOptions.ToString()` omits it
- Uploads take a `Stream` and never buffer it whole. `FileSystemStorage` streams to `tmp/` with an
  incremental MD5 hash, calls `Flush(true)`, then `File.Move(overwrite: true)`. Capture `FileInfo`
  attributes before the move, because `FileInfo` loads them lazily from the path. `AzureBlobStorage`
  uses `BlobClient.UploadAsync` with `StorageTransferOptions` (block staging). `GetBlobsAsync` in
  `Azure.Storage.Blobs` 12.29 requires `states:` explicitly when you pass `traits:`/`prefix:` by name.
  C# forbids `yield` inside a `try` that has a `catch`, which is why `ListAsync` guards only
  `MoveNextAsync`
- Tests (`GraphPlatform.Api.Tests/Storage/`): `StorageContractTests` is an abstract base with
  `[SkippableFact]`/`[SkippableTheory]` from `Xunit.SkippableFact`, needed because xunit 2.x has no
  runtime skip. `FileSystemStorageContractTests` and `AzureBlobStorageContractTests` derive from it;
  the Azure variant skips unless `AZURITE_CONNECTION_STRING` is set. The folder also holds
  `FileSystemStorageTests` and `StorageOptionsTests`, which cover DI, fail-fast startup and secret
  redaction. `GraphPlatformApiFactory` points `Storage:FileSystem:Root` at a per-factory temp directory

### CORS

The SPA in `src/frontend` runs on a different origin, so `Program.cs` registers a named policy
(`Program.SpaCorsPolicy`, `"spa"`) and calls `app.UseCors(...)` **after** `UseHttpsRedirection()` and
**before** `UseAuthentication()` — authorization runs on the principal authentication puts in place,
and a rejected preflight must still carry the CORS headers.

- Origins come from `Cors:AllowedOrigins` (a string array), falling back to `http://localhost:5173`
  and `http://localhost:4173` (Vite dev and preview) when the section is empty. They are enumerated
  rather than wildcarded because `AllowCredentials()` forbids `AllowAnyOrigin()`.
- `WithExposedHeaders("Content-Disposition")` is required: without it the browser hides that header
  from `fetch`, and the file-download path cannot read the server's filename.

### Testing, and the `dotnet test` gotcha
- `dotnet test src/api/GraphPlatform.slnx` runs the integration tests through `WebApplicationFactory`
  with the DbContext swapped for in-memory SQLite (`EnsureCreated`, since the Npgsql migration cannot
  run there) — no PostgreSQL or network needed.
- Use **xunit 2.x + `Microsoft.NET.Test.Sdk` + `xunit.runner.visualstudio`**. xunit.v3 4.x is
  Microsoft.Testing.Platform-based, and on .NET 10 the SDK both refuses to drive MTP through VSTest
  ("Testing with VSTest target is no longer supported ... on .NET 10 SDK and later") and failed the
  MTP server-mode handshake here (the `global.json` `test.runner` opt-in produced zero tests and exit
  code 5, with or without `UseMicrosoftTestingPlatformRunner`). The VSTest combination needs no extra
  configuration.
- SQLite covers model/DTO/validation/authorization behaviour. Not executed: applying the migration to
  a live PostgreSQL (no local server was available), so the Npgsql `jsonb` round-trip rests on
  Npgsql's documented mapping rather than a runtime check.

## Frontend (`src/frontend`, React)

**GraphForge** is the Vite + React 19 + TypeScript SPA that drives the management API. It is not a
uv project and imports nothing from `common`; its only contract with the rest of the repo is the
HTTP surface of `src/api`.

### Stack and build

Vite 8, React 19.2 with the **React Compiler** (via `@rolldown/plugin-babel` + `reactCompilerPreset()`),
TypeScript 6, ESLint 10 flat config, Tailwind v4, shadcn/ui (`radix-nova` style), React Router 7,
TanStack Query 5, React Hook Form + Zod 4, and Lucide icons. npm is the package manager.

```bash
cd src/frontend
npm run dev      # Vite dev server on :5173
npm run lint     # ESLint, including the React Compiler rules
npx tsc -b       # type-check
npm run build    # tsc -b && vite build
```

- **The `@/*` alias is declared in three places** and all three must agree: the reference-only root
  `tsconfig.json` (the shadcn CLI reads it and aborts without it), `tsconfig.app.json` (what the
  editor and `tsc -b` honour), and `resolve.alias` in `vite.config.ts` via
  `fileURLToPath(new URL('./src', import.meta.url))`, since `"type": "module"` means no `__dirname`.
  Do **not** add `baseUrl` — TypeScript 6 errors on it as deprecated; bare `paths` is enough.
- Tailwind v4 is CSS-configured. There is no `tailwind.config.js`, and `components.json` carries
  `"tailwind": { "config": "" }`. Design tokens live at the top of `src/index.css`.
- `tsconfig.app.json` sets `erasableSyntaxOnly`, so **no TypeScript `enum`** and no constructor
  parameter properties. API enums are modelled as a const object plus a derived union in
  `src/api/types.ts`; `ApiError`'s fields are assigned longhand.
- `verbatimModuleSyntax` makes a value-style import of a type a build error (TS1484), which the
  shadcn registry emits routinely. `@typescript-eslint/consistent-type-imports` is enabled, so run
  `npx eslint src --fix && npx tsc -b` after every `shadcn add`.
- `src/components/ui/**` is generated: it has its own ESLint override disabling
  `react-refresh/only-export-components`, and must not be hand-edited (`--overwrite` would undo it).

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `VITE_APP_NAME` | `GraphForge` | Brand text and `<title>` (substituted into `index.html` as `%VITE_APP_NAME%`) |
| `VITE_API_BASE_URL` | `http://localhost:5087` | Absolute API origin |
| `VITE_MAX_UPLOAD_BYTES` | `104857600` | Client-side upload guard; mirrors `FileUploads:MaxFileSizeBytes` |

Committed defaults live in `.env` (not only `.env.example`): Vite substitutes `%VITE_*%` in HTML
**only** for variables that are actually defined, so a missing `VITE_APP_NAME` renders the literal
token. Local overrides go in `.env.local`, which is gitignored. `src/app/env.ts` reads and
normalises all three once.

### Structure

`src/app` (providers, router, query client, env) · `src/api` (typed client: `http.ts`, `errors.ts`,
`token-store.ts`, `types.ts`, `endpoints/`) · `src/auth` · `src/org` · `src/queries` (one hook
module per resource, plus `keys.ts`) · `src/schemas` (Zod) · `src/components`
(`ui/` generated, plus `layout/`, `feedback/`, `data/`, `form/`) · `src/features` · `src/routes`.

### Patterns worth knowing

- **The API's failure shapes are not uniform, and `errors.ts` must not assume JSON.** `Forbid()` and
  the JWT middleware return **403/401 with an empty body**; explicit failures return `ProblemDetails`;
  model validation returns `ValidationProblemDetails`, identified by its `errors` key. A `fetch`
  rejection maps to `status: 0`, which the UI renders as "cannot reach the server" rather than as a
  server error.
- **Validation keys are mixed-case.** `IValidatableObject` results use `nameof(ApiKey)` (PascalCase),
  model-bound failures are camelCase, body-parse failures key on `"$"`, and upload failures on
  `"file"`. `getFieldErrors()` emits each key verbatim *and* camelCased, collecting anything
  unattributable under `ROOT_ERROR_KEY`.
- **Uploads use `XMLHttpRequest`, not `fetch`** — only XHR reports upload progress, and files run to
  100 MiB. The multipart field name must be exactly `file`, and `Content-Type` is never set manually
  so the browser can generate the boundary.
- **Downloads need the bearer header**, so a plain `<a href>` cannot work: content is fetched as a
  blob and saved via an object URL, revoked in a `setTimeout(…, 0)` because revoking synchronously
  cancels the download in Safari.
- **There is no refresh token and the access token lasts 60 minutes.** `AuthProvider` arms a warning
  toast at T−5 min and a hard logout at T−30 s, re-arming both on `visibilitychange`; a 401 from any
  request triggers one logout via a re-entrancy-guarded handler. Login and signup pass
  `skipAuthRedirect`, because a 401 there is a bad password, not an expired session.
- **The organization lives in the URL** (`/orgs/:organizationId/...`), never in global state, so a
  query key can never disagree with what is rendered. The sidebar switcher navigates; `lastOrgId` in
  `localStorage` is only a redirect hint for `/`.
- **Roles come from `GET /api/auth/me`**, not from the JWT — the API resolves them per request, so
  token-derived roles would go stale. `src/org/permissions.ts` mirrors `OrganizationAccessService`
  (`canAuthor`, `canGovern`) by name so drift is visible in review.
- **Gating is disabled-with-a-reason, not hidden**, except for whole sections a role can never use
  (Settings, Members). Three server 409s are mirrored client-side: draft-only knowledge bases, the
  last remaining admin, and deleting the active embedding model. Because a natively `disabled`
  button fires no pointer events (so a tooltip on it never opens), `ActionTooltip` wraps such
  controls in a focusable span.
- **Editing a model replaces it wholesale, so `apiKey` is always required, even to change an
  unrelated field.** The edit form therefore requires re-entering it, shows a warning, and never
  renders a fake `••••` value. `ModelForm` has no authentication-mode selector at all — the API only
  ever authenticates with an API key, so `authMode` is not part of `ModelWriteRequest`/
  `FormValues`/`modelEditSchema`; `AuthMode` remains only on the read-only `ModelDto` (always
  `api_key`), consumed by `ModelDetailPage`/`ModelsTable`'s existing display branches.
- **No resource id is ever collected or displayed in the UI.** A Model's `id` (like a Knowledge
  Base's) is optional on `CreateModelRequest` and generated by the API when omitted
  (`ModelsController.CreateModel`); the frontend never sends one. `ModelForm` therefore has no
  identifier field, in either mode — `modelEditSchema` is shared by create and edit — and the
  create/edit `id` field, the "Regenerate"/"Use a custom id" buttons and `lib/uuid.ts`'s `isUuid`
  helper were removed with it. Detail pages (`ModelDetailPage`, `KnowledgeBaseDetailPage`) don't
  render the id either; both dropped their "Identifier" `dt`/`dd` block and `CopyButton`, which left
  each summary `dl` one column narrower. `newUuid()` survives only as a client-only React key
  generator for the upload queue in `KnowledgeBaseDetailPage` — that id is never sent to the API.
- **A model's capabilities are validated client-side to match `ModelWriteRequest.Validate`
  exactly**: `modelEditSchema`'s `superRefine` requires at least one `type` entry and rejects
  `embedding` combined with `vision`/`thinking`. `ModelForm`'s capability checkboxes enforce the
  same exclusivity proactively rather than only after submit — checking Embedding deselects
  Vision/Thinking (and vice versa) instead of allowing both, since an embedding model is a
  different litellm call shape than a chat model and cannot be both. Neither the embedding
  dimension nor the reasoning effort field renders until at least one capability is checked; which
  one appears then follows `isEmbedding`, same as before.
- **No list endpoint supports search, filtering or pagination**, so `useClientCollection` does all of
  it over the fetched array. That is a deliberate stopgap: lists in the thousands are the point at
  which this needs to become a server-side capability.
- **Polling is self-terminating**: `refetchInterval` is the function form, returning 5 s only while a
  knowledge base is `indexing` or a file is `uploaded`/`processing`, and `false` otherwise.
- **React Compiler forbids synchronous `setState` in an effect.** Dialogs therefore rely on Radix
  unmounting their content on close to reset form state (the body is a child component) rather than a
  reset-on-close effect, `useIsMobile` uses `useSyncExternalStore`, and `ModelForm` uses `useWatch`
  rather than `form.watch()`, which returns an unmemoizable function and makes the compiler skip the
  whole component.
- Accessibility: a skip link, `<main tabIndex={-1}>` focused on every route change (React Router does
  not move focus by itself), one `Toaster` plus a separate `aria-live` announcer for filter counts and
  upload/indexing transitions, `DialogTitle` on every dialog, and `AlertDialog` for destructive
  confirmations. Status is never conveyed by colour alone.
