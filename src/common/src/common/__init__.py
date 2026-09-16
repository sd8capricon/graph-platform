"""Shared library for the graphrag-apacheage services.

Holds only what more than one service needs (see ADR-0004 Decision 4):
configuration, domain schemas, ORM models, repositories, the embedding service
and the per-model embedding index DDL. Service-specific code - the agent runtime
and the ingestion worker - lives in its own uv project under `src/`. This module
deliberately re-exports nothing: import leaf modules directly
(`from common.services.embedding_service import EmbeddingService`), never
`from common import ...`.
"""
