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
   - `Model` (`schemas/model.py`): Configured LLM/embedding provider connection (name, provider,
     connection_string, auth_mode, type capabilities, api_key, embedding_dimension) —
     validates that `api_key` is set when `auth_mode` is `api_key` and `embedding_dimension`
     is set when `embedding` is in `type`. Passed into `EmbeddingService.compute_embeddings()`
     to describe which provider/model to call.

2. **Models** (`src/graphrag_apacheage/models/`)
   - `Base` (`models/base.py`): shared SQLAlchemy `DeclarativeBase` for all ORM models
   - `GraphSchemaRegistry`: SQLAlchemy ORM model tracking node/relationship type definitions
   - Stores: graph name, entity type, name, description, aliases, properties, source/target labels
   - Core method: `upsert_records()` - merges new schemas with existing definitions
   - `NodeEmbedding`: SQLAlchemy ORM model storing one vector embedding per knowledge base node
   - Stores: graph name, node ID, label, properties snapshot, embedding vector
   - Core methods: `upsert_records()` - inserts/updates node embeddings; `vector_search()` - cosine-similarity search
   - Both models share the pgvector embedding column pattern and delegate embedding computation
     to `EmbeddingService`; see "Vector Embedding & Search Pattern" below

3. **Agents** (`src/graphrag_apacheage/agent/`)
   - `tools.py` - placeholder for agent tool implementations (currently empty)
   - Intended for: LLM-based agent tools that interact with the knowledge graph

4. **Services** (`src/graphrag_apacheage/services/`)
   - `KnowledgeBaseService`: High-level service for knowledge base operations
   - `EmbeddingService` (`services/embedding_service.py`): Computes text embeddings via litellm,
     shared by any ORM model with a vector embedding column

5. **Repositories** (`src/graphrag_apacheage/repositories/`)
   - `AgeGraphRepository`: Data access layer for Apache Age graph operations

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
- **UUID generation**: Node and relationship IDs are auto-generated as UUIDs if not provided
- Uses `@model_validator(mode="before")` in Pydantic models to ensure IDs exist
- See: `KnowledgeNode.ensure_id()`, `KnowledgeRelationship.ensure_related_ids()`

### Schema Registry Pattern
- `GraphSchemaRegistry.upsert_records()` performs smart merging:
  - Creates new records if not found
  - Merges aliases: `existing.aliases = sorted(set(existing.aliases) | set(record.aliases))`
  - Merges properties: `existing.properties = sorted(set(existing.properties) | set(record.properties))`
  - Preserves source/target labels if not yet set
- `KnowledgeBase.get_graph_schema_registry_records(graph_name)` extracts schema records
  - Requires `graph_name` parameter (not stored on model, passed to method)
  - Returns list of `GraphSchemaRegistry` records for nodes and relationships
- See: `src/graphrag_apacheage/models/graph_schema_regsitry.py` and `src/graphrag_apacheage/schemas/knowledge_base.py`

### Vector Embedding & Search Pattern
- Both `GraphSchemaRegistry` and `NodeEmbedding` (`models/node_embedding.py`) store a pgvector `embedding` column (`Vector(settings.embedding_dimension).with_variant(JSON, "sqlite")`), sized from the `settings` singleton (`config.py`, `AppSettings.embedding_dimension`, default `1536`) — both ORM models import `settings` directly from `config.py` (not from `embedding_service.py`, and not from an env var) so tests run against SQLite (embedding stored as JSON) while production uses PostgreSQL + pgvector
  - `AppSettings` (`config.py`) is a pydantic `BaseModel` holding app config, and loads YAML in its constructor: `AppSettings(path)` reads `embedding_dimensions` from the file (see `configs/local.yaml`) into `embedding_dimension`, `AppSettings()` uses field defaults, and explicit kwargs (`AppSettings(path, embedding_dimension=768)`) win over the file
  - The module-level `config.load_config(path)` function constructs `AppSettings(path)` and reassigns the `settings` singleton — call it before `models/graph_schema_registry.py` or `models/node_embedding.py` are first imported anywhere, since pgvector's `Vector` column size is fixed at class-definition time
- Embeddings are computed by `EmbeddingService.compute_embeddings(model, texts)` (`services/embedding_service.py`) via `litellm.aembedding()` — both ORM models import `EmbeddingService` from there instead of defining their own copies
  - Takes an explicit `model: Model | None` (see `schemas/model.py`) describing the provider — builds the litellm model string as `f"{model.provider}/{model.name}"`, passes `connection_string` as `api_base`, `api_key.get_secret_value()` as `api_key` when `auth_mode` is `api_key`, and `embedding_dimension` as `dimensions`
  - If `model` is `None` (or `texts` is empty), embedding is skipped entirely (returns `None`) so callers without a configured provider are unaffected — there is no global env var fallback
- Each ORM model builds its own `embedding_text()` (name/description/aliases for `GraphSchemaRegistry`; label + `"key: value"` properties for `NodeEmbedding`) and (re)computes it inside `upsert_records(session, records, model=...)` after merging/updating fields, by calling `EmbeddingService.compute_embeddings(model, texts)`
- `vector_search(session, query, graph_name, model, ..., limit=5)` embeds the query text via the given `model`, then orders rows with pgvector's cosine distance operator: `cls.embedding.cosine_distance(embedding)` — requires PostgreSQL, raises `ValueError` if `model` is `None`
- `KnowledgeBase.get_node_embedding_records(graph_name)` builds one unsaved `NodeEmbedding` per node (keyed by `graph_name` + `node_id`); `KnowledgeBaseService.upsert_node_embeddings(session, kb, graph_name, model=None)` / `.search_nodes(session, query, graph_name, model, ...)` wrap the upsert/search calls and pass `model` straight through (upsert defaults to `None` — skip embedding; search requires a `model`)
- Tests monkeypatch `embedding_service.litellm.aembedding` (import the module as `embedding_service`, not the individual ORM model modules) and pass a `Model` built via a small `_embedding_model()` test helper, to avoid real API calls
- See: `src/graphrag_apacheage/services/embedding_service.py`, `src/graphrag_apacheage/schemas/model.py`, `src/graphrag_apacheage/models/node_embedding.py`, and `tests/test_embedding_service.py` / `tests/test_node_embedding_model.py`

### Validation & Constraints
- Type constraint in GraphSchemaRegistry: `type IN ('node', 'relationship')` via CheckConstraint
- Tests verify this constraint is enforced: `test_graph_registry_type_accepts_only_node_or_relationship()`

## Common Tasks

### Adding a New Schema Type
1. Update `SchemaType` enum in `models/graph_schema_regsitry.py`
2. Add CheckConstraint to `GraphSchemaRegistry.__table_args__`
3. Add test in `tests/test_graph_registry_model.py`

### Loading and Registering a Knowledge Base
```python
from sqlalchemy.ext.asyncio import AsyncSession

kb = KnowledgeBase.from_json_file("path/to/kb.json")
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
- `tests/test_graph_registry_model.py` - test suite (schema registry, general KnowledgeBase/service behavior)
- `tests/test_node_embedding_model.py` - test suite for `NodeEmbedding` and node vector search
- `tests/test_embedding_service.py` - test suite for the shared `EmbeddingService`
- `dummy_data/f1_kb.json` - example knowledge base (Formula 1)

### Running Tests
```bash
pytest tests/
```

### Project Dependencies
- **pydantic** (>=2.13.5): Data validation and serialization
- **sqlalchemy[asyncio]** (>=2.0.42): ORM and database abstraction (async engine/session)
- **psycopg2-binary** (>=2.9.12): PostgreSQL/Apache Age connection
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
- Example data: `dummy_data/f1_kb.json` (Formula 1 knowledge base)

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
