"""Service implementations.

Intentionally re-exports nothing. `models/graph_schema_registry.py` imports
`services.embedding_service`, and any `services.*` import runs this file first — so
re-exporting `knowledge_base_service` here closes a cycle back through
`schemas.knowledge_base` -> `models.graph_schema_registry`. Import leaf modules directly.
"""
