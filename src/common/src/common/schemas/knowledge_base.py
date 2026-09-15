from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from common.models.graph_schema_registry import (
    GraphSchemaRegistry,
    SchemaType,
)
from common.models.node_embedding import NodeEmbedding


class KnowledgeNode(BaseModel):
    """Represents a node in a knowledge graph.

    A node is a vertex in the graph with a unique identifier, a semantic label,
    and optional properties for storing metadata.

    Attributes:
        id: Unique identifier for the node. Auto-generated as UUID if not provided.
        label: The semantic label or type of the node (e.g., 'Person', 'Organization').
        properties: A dictionary of key-value pairs storing node metadata.
    """

    id: str | None = None
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def ensure_id(cls, data: Any) -> Any:
        """Ensure that the node has an ID by generating a UUID if not provided.

        Args:
            data: The raw data dictionary before model instantiation.

        Returns:
            The data dictionary with id field populated (generated if necessary).
        """
        if isinstance(data, dict):
            data = dict(data)
            data.setdefault("id", str(uuid4()))
        return data


class KnowledgeRelationship(BaseModel):
    """Represents a directed edge connecting two nodes in a knowledge graph.

    A relationship is a directed connection between two nodes with a semantic label
    and optional properties for storing relationship metadata.

    Attributes:
        source_id: The unique identifier of the source (starting) node.
        target_id: The unique identifier of the target (ending) node.
        label: The semantic label or type of the relationship (e.g., 'knows', 'works_for').
        properties: A dictionary of key-value pairs storing relationship metadata.
    """

    source_id: str | None = None
    target_id: str | None = None
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def ensure_related_ids(cls, data: Any) -> Any:
        """Ensure that source_id and target_id exist by generating UUIDs if not provided.

        Args:
            data: The raw data dictionary before model instantiation.

        Returns:
            The data dictionary with source_id and target_id fields populated
            (generated if necessary).
        """
        if isinstance(data, dict):
            data = dict(data)
            data.setdefault("source_id", str(uuid4()))
            data.setdefault("target_id", str(uuid4()))
        return data


class KnowledgeBase(BaseModel):
    """A container for nodes and relationships that form a knowledge graph.

    Represents a complete knowledge graph with a name, unique identifier, and
    collections of nodes and their relationships.

    Attributes:
        id: Unique identifier for the knowledge base. Auto-generated as UUID if not provided.
        name: The name or identifier of the knowledge base.
        nodes: A list of KnowledgeNode instances in the graph.
        relationships: A list of KnowledgeRelationship instances in the graph.
    """

    id: str | None = None
    name: str
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    relationships: list[KnowledgeRelationship] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def ensure_knowledge_base_id(cls, data: Any) -> Any:
        """Ensure that the knowledge base has an ID by generating a UUID if not provided.

        Args:
            data: The raw data dictionary before model instantiation.

        Returns:
            The data dictionary with id field populated (generated if necessary).
        """
        if isinstance(data, dict):
            data = dict(data)
            data.setdefault("id", str(uuid4()))
        return data

    @classmethod
    def from_json_file(cls, file_path: str | Path) -> "KnowledgeBase":
        """Load a KnowledgeBase from a JSON file.

        Args:
            file_path: Path to the JSON file containing the knowledge base data.

        Returns:
            A KnowledgeBase instance deserialized from the JSON file.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the JSON content is invalid or does not match the schema.
        """
        return cls.model_validate_json(Path(file_path).read_text())

    def get_graph_schema_registry_records(
        self, graph_name: str, organization_id: str
    ) -> list[GraphSchemaRegistry]:
        """Extract schema registry records from the knowledge base.

        Analyzes all nodes and relationships in the knowledge base to generate
        schema registry records that catalog entity types, relationship types,
        properties, and aliases for database storage.

        Args:
            graph_name: The name of the Apache Age graph these schemas belong to.
            organization_id: Id of the organization these schemas belong to (see
                ADR-0002, Decision 1). Stamped onto every constructed record.

        Returns:
            A list of GraphSchemaRegistry records representing node and relationship
            type definitions extracted from the knowledge base.

        Raises:
            ValueError: If this knowledge base has no id, or if organization_id
                is not provided.
        """
        if not self.id:
            raise ValueError(
                "id is required on the knowledge base when building graph schema "
                "registry records"
            )
        if not organization_id:
            raise ValueError(
                "organization_id is required when building graph schema registry "
                "records"
            )
        knowledge_base_id = self.id

        grouped: dict[tuple[str, str, str], GraphSchemaRegistry] = {}

        for node in self.nodes:
            key = (graph_name, SchemaType.NODE.value, node.label)
            row = grouped.setdefault(
                key,
                GraphSchemaRegistry(
                    organization_id=organization_id,
                    graph_name=graph_name,
                    knowledge_base_ids=[knowledge_base_id],
                    type=SchemaType.NODE,
                    name=node.label,
                    description="",
                    aliases=[],
                    properties=list(node.properties.keys()),
                    source_label=None,
                    target_label=None,
                ),
            )
            row.properties = sorted(set(row.properties) | set(node.properties.keys()))

        for relationship in self.relationships:
            source_label = next(
                (
                    node.label
                    for node in self.nodes
                    if node.id == relationship.source_id
                ),
                None,
            )
            target_label = next(
                (
                    node.label
                    for node in self.nodes
                    if node.id == relationship.target_id
                ),
                None,
            )
            key = (graph_name, SchemaType.RELATIONSHIP.value, relationship.label)
            row = grouped.setdefault(
                key,
                GraphSchemaRegistry(
                    organization_id=organization_id,
                    graph_name=graph_name,
                    knowledge_base_ids=[knowledge_base_id],
                    type=SchemaType.RELATIONSHIP,
                    name=relationship.label,
                    description="",
                    aliases=[],
                    properties=list(relationship.properties.keys()),
                    source_label=source_label,
                    target_label=target_label,
                ),
            )
            row.properties = sorted(
                set(row.properties) | set(relationship.properties.keys())
            )
            row.source_label = source_label or row.source_label
            row.target_label = target_label or row.target_label

        return list(grouped.values())

    def get_node_embedding_records(
        self, graph_name: str, organization_id: str
    ) -> list[NodeEmbedding]:
        """Extract node embedding records from the knowledge base.

        Builds one NodeEmbedding record per node, capturing its label and properties
        so an embedding can be computed and stored for similarity search.

        Args:
            graph_name: The name of the Apache Age graph these nodes belong to.
            organization_id: Id of the organization these nodes belong to (see
                ADR-0002, Decision 1). Stamped onto every constructed record.

        Returns:
            A list of NodeEmbedding records, one per node in the knowledge base.

        Raises:
            ValueError: If this knowledge base has no id, or if organization_id
                is not provided.
        """
        if not self.id:
            raise ValueError(
                "id is required on the knowledge base when building node embedding "
                "records"
            )
        if not organization_id:
            raise ValueError(
                "organization_id is required when building node embedding records"
            )
        knowledge_base_id = self.id

        return [
            NodeEmbedding(
                organization_id=organization_id,
                graph_name=graph_name,
                knowledge_base_id=knowledge_base_id,
                node_id=node.id,
                label=node.label,
                properties=dict(node.properties),
            )
            for node in self.nodes
        ]


__all__ = [
    "KnowledgeBase",
    "KnowledgeNode",
    "KnowledgeRelationship",
]
