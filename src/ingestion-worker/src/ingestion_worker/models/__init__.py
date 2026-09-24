"""SQLAlchemy Core table definitions for the ingestion job-state tables.

Deliberately outside `common` (ADR-0004 Decision 4: only the ingestion worker
needs them) and deliberately **not** ORM models on `common.models.base.Base`:
EF owns the DDL for `index_job`/`index_file`/`knowledge_base` (ADR-0005), so
they are declared as Core `Table`s on the private `IndexJobMetadata` and
imported leaf-by-leaf, mirroring the `common/models/` layout.
"""