"""Declarative ORM models for ingestion job-state tables.

`IndexJob` and `IndexFile` are mapped on the worker's private `IndexJobBase`,
separate from common's Python-owned and API-owned metadata. The shared API-owned
`knowledge_base` mapping remains in `common.models.knowledge_base`.
"""
