# Agent Customization for graphrag-apacheage

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

2. **Models** (`src/graphrag_apacheage/models/`)
   - `GraphSchemaRegistry`: SQLAlchemy ORM model tracking node/relationship type definitions
   - Stores: graph name, entity type, name, description, aliases, properties, source/target labels
   - Core method: `upsert_records()` - merges new schemas with existing definitions

3. **Agents** (`src/graphrag_apacheage/agent/`)
   - `tools.py` - placeholder for agent tool implementations (currently empty)

### Data Flow

```
JSON File → KnowledgeBase → get_graph_schem_registry_records() → 
  → GraphSchemaRegistry list → upsert_records() → Database
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
- See: `src/graphrag_apacheage/models/graph_schema_regsitry.py` lines 36-72

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
kb = KnowledgeBase.from_json_file("path/to/kb.json")
schema_records = kb.get_graph_schem_registry_records()
# Insert to database via GraphSchemaRegistry.upsert_records(session, schema_records)
```

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
- `tests/test_graph_registry_model.py` - test suite
- `dummy_data/f1_kb.json` - example knowledge base (Formula 1)

### Running Tests
```bash
pytest tests/
```

### Project Dependencies
- **pydantic** (>=2.13.5): Data validation and serialization
- **sqlalchemy** (>=2.0.42): ORM and database abstraction
- **psycopg2-binary** (>=2.9.12): PostgreSQL/Apache Age connection

## Important Notes

### Naming Quirks
- File: `graph_schema_regsitry.py` (note: "regsitry" not "registry" - appears to be intentional)
- When referencing this module, preserve the exact spelling

### Testing Strategy
- Tests use SQLite in-memory databases (no PostgreSQL required)
- Tests validate schema structure, constraints, and upsert logic
- Example: `test_knowledge_base_parses_json_and_upserts_registry_rows()` uses `dummy_data/f1_kb.json`

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
