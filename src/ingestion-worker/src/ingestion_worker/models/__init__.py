"""SQLAlchemy Core table definitions for ingestion job-state tables.

The ingestion-only `index_job` and `index_file` definitions stay here on private
`IndexJobMetadata`. The API-owned `knowledge_base` mapping is shared from
`common.models.knowledge_base` and uses separate metadata so regular common ORM
table creation does not claim API-owned DDL.
"""
