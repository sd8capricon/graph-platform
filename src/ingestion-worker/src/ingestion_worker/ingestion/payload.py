"""Worker-owned parsing for pre-extracted upload JSON.

The uploaded file (see ``dummy_data/f1_kb.json``) already contains the complete
``nodes``/``relationships`` payload plus a temporary ``schema`` block
(``labels``/``relationships``/``triplets``). That ``schema`` block is **not**
part of the shared ``common.schemas.knowledge_base.KnowledgeBase`` contract and
must never be added there: it is transient ingestion input, consumed here to
build ``GraphSchemaRegistryDTO`` rows and then discarded.

``nodes``/``relationships`` *are* the knowledge-base contract, so this module
reuses ``common``'s ``KnowledgeNode``/``KnowledgeRelationship`` shapes only via
strict worker-local file models (required ids) and converts them into the
shared ``KnowledgeBase``/``NodeEmbeddingDTO`` types. Nothing in ``common`` is
modified.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from common.schemas.graph_schema_registry import GraphSchemaRegistryDTO, SchemaType
from common.schemas.knowledge_base import KnowledgeBase
from common.schemas.node_embedding import NodeEmbeddingDTO


class TempLabelDef(BaseModel):
    """One ``schema.labels[]`` entry of the temporary upload block."""

    name: str
    properties: dict[str, Any] = Field(default_factory=dict)


class TempRelationshipDef(BaseModel):
    """One ``schema.relationships[]`` entry of the temporary upload block."""

    name: str
    properties: dict[str, Any] = Field(default_factory=dict)


class TempTriplet(BaseModel):
    """One ``schema.triplets[]`` entry linking source/relationship/target labels."""

    source: str
    relationship: str
    target: str


class TempSchemaBlock(BaseModel):
    """The temporary ``schema`` block: labels, relationships and triplets."""

    labels: list[TempLabelDef] = Field(default_factory=list)
    relationships: list[TempRelationshipDef] = Field(default_factory=list)
    triplets: list[TempTriplet] = Field(default_factory=list)


class FileNode(BaseModel):
    """Strict file-level node: ids are required, never auto-generated.

    ``common``'s ``KnowledgeNode`` generates a UUID when ``id`` is omitted,
    which would duplicate entities on retry. The upload contract provides
    deterministic ids (as in ``f1_kb.json``), so a missing id is a permanent
    input error, not something to repair here.
    """

    id: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class FileRelationship(BaseModel):
    """Strict file-level relationship: endpoint ids and label are required."""

    source_id: str
    target_id: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class UploadedKbFile(BaseModel):
    """One uploaded JSON file: KB payload plus the temporary ``schema`` block."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    name: str = ""
    schema_block: TempSchemaBlock | None = Field(default=None, alias="schema")
    nodes: list[FileNode] = Field(default_factory=list)
    relationships: list[FileRelationship] = Field(default_factory=list)


def parse_uploaded_file(data: bytes | str) -> UploadedKbFile:
    """Parse raw upload bytes into an :class:`UploadedKbFile`.

    Raises:
        ValueError: If the bytes are not UTF-8 JSON or fail validation.
            Callers classify this as non-retryable (no retryable markers).
    """
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"uploaded file is not valid UTF-8: {exc}") from exc
    else:
        text = data
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"uploaded file is not valid JSON: {exc}") from exc
    try:
        envelope = UploadedKbFile.model_validate(raw)
    except Exception as exc:
        raise ValueError(f"uploaded file does not match the expected format: {exc}") from exc
    for node in envelope.nodes:
        if not node.id or not node.id.strip():
            raise ValueError("uploaded file contains a node with a blank id")
        if not node.label or not node.label.strip():
            raise ValueError("uploaded file contains a node with a blank label")
    for rel in envelope.relationships:
        if not rel.label or not rel.label.strip():
            raise ValueError("uploaded file contains a relationship with a blank label")
        if not rel.source_id or not rel.target_id:
            raise ValueError("uploaded file contains a relationship with a blank endpoint id")
    if envelope.schema_block is not None:
        for label in envelope.schema_block.labels:
            if not label.name or not label.name.strip():
                raise ValueError("uploaded file schema contains a label with a blank name")
        for rel in envelope.schema_block.relationships:
            if not rel.name or not rel.name.strip():
                raise ValueError("uploaded file schema contains a relationship with a blank name")
    return envelope


def to_knowledge_base(
    envelope: UploadedKbFile, knowledge_base_id: str, name: str | None = None
) -> KnowledgeBase:
    """Convert the envelope's nodes/relationships into a shared ``KnowledgeBase``.

    The job row's ``knowledge_base_id`` is authoritative; the file's own ``id``
    (if present and different) is overridden by the caller. The temporary
    ``schema`` block is ignored here.
    """
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id is required to build a knowledge base")
    kb_name = name or envelope.name or knowledge_base_id
    return KnowledgeBase.model_validate(
        {
            "id": knowledge_base_id,
            "name": kb_name,
            "nodes": [
                {"id": node.id, "label": node.label, "properties": dict(node.properties)}
                for node in envelope.nodes
            ],
            "relationships": [
                {
                    "source_id": rel.source_id,
                    "target_id": rel.target_id,
                    "label": rel.label,
                    "properties": dict(rel.properties),
                }
                for rel in envelope.relationships
            ],
        }
    )


def to_schema_registry_records(
    envelope: UploadedKbFile,
    graph_name: str,
    organization_id: str,
    knowledge_base_id: str,
) -> list[GraphSchemaRegistryDTO]:
    """Build registry DTOs from the temporary ``schema`` block (not by derivation).

    Property lists come from the block's ``properties`` keys; relationship
    source/target labels come from ``triplets`` (first matching triplet wins,
    mirroring the extraction fallback). A missing ``schema`` block yields no
    rows -- callers must not fall back to deriving from instances.
    """
    if not organization_id:
        raise ValueError("organization_id is required for schema registry records")
    if not graph_name:
        raise ValueError("graph_name is required for schema registry records")
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id is required for schema registry records")
    if envelope.schema_block is None:
        return []

    triplet_by_rel: dict[str, TempTriplet] = {}
    for triplet in envelope.schema_block.triplets:
        triplet_by_rel.setdefault(triplet.relationship, triplet)

    records: list[GraphSchemaRegistryDTO] = []
    for label in envelope.schema_block.labels:
        records.append(
            GraphSchemaRegistryDTO(
                organization_id=organization_id,
                graph_name=graph_name,
                knowledge_base_ids=[knowledge_base_id],
                type=SchemaType.NODE,
                name=label.name,
                description="",
                aliases=[],
                properties=sorted(label.properties.keys()),
                source_label=None,
                target_label=None,
            )
        )
    for rel in envelope.schema_block.relationships:
        triplet = triplet_by_rel.get(rel.name)
        records.append(
            GraphSchemaRegistryDTO(
                organization_id=organization_id,
                graph_name=graph_name,
                knowledge_base_ids=[knowledge_base_id],
                type=SchemaType.RELATIONSHIP,
                name=rel.name,
                description="",
                aliases=[],
                properties=sorted(rel.properties.keys()),
                source_label=triplet.source if triplet else None,
                target_label=triplet.target if triplet else None,
            )
        )
    return records


def to_node_embedding_records(
    envelope: UploadedKbFile,
    graph_name: str,
    organization_id: str,
    knowledge_base_id: str,
) -> list[NodeEmbeddingDTO]:
    """Build one ``NodeEmbeddingDTO`` per node in the envelope."""
    if not organization_id:
        raise ValueError("organization_id is required for node embedding records")
    if not graph_name:
        raise ValueError("graph_name is required for node embedding records")
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id is required for node embedding records")
    return [
        NodeEmbeddingDTO(
            organization_id=organization_id,
            graph_name=graph_name,
            knowledge_base_id=knowledge_base_id,
            node_id=node.id,
            label=node.label,
            properties=dict(node.properties),
        )
        for node in envelope.nodes
    ]


__all__ = [
    "UploadedKbFile",
    "TempSchemaBlock",
    "TempLabelDef",
    "TempRelationshipDef",
    "TempTriplet",
    "FileNode",
    "FileRelationship",
    "parse_uploaded_file",
    "to_knowledge_base",
    "to_schema_registry_records",
    "to_node_embedding_records",
]
