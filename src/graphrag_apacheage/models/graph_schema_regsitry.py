from collections.abc import Iterable
from enum import Enum

from sqlalchemy import JSON, CheckConstraint, String, Text, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class SchemaType(str, Enum):
    NODE = "node"
    RELATIONSHIP = "relationship"


class GraphSchemaRegistry(Base):
    __tablename__ = "graph_registry"
    __table_args__ = (
        CheckConstraint(
            "type IN ('node', 'relationship')", name="ck_graph_registry_type"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    graph_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    type: Mapped[SchemaType] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    properties: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    @classmethod
    def upsert_records(
        cls, session: Session, records: Iterable[GraphSchemaRegistry]
    ) -> list[GraphSchemaRegistry]:
        persisted: list[GraphSchemaRegistry] = []

        for record in records:
            existing = session.execute(
                select(cls).where(
                    cls.graph_name == record.graph_name,
                    cls.type
                    == (
                        record.type.value
                        if isinstance(record.type, SchemaType)
                        else record.type
                    ),
                    cls.name == record.name,
                )
            ).scalar_one_or_none()

            if existing is None:
                session.add(record)
                persisted.append(record)
                continue

            existing.description = record.description
            existing.aliases = sorted(set(existing.aliases) | set(record.aliases))
            existing.properties = sorted(
                set(existing.properties) | set(record.properties)
            )
            existing.source_label = record.source_label or existing.source_label
            existing.target_label = record.target_label or existing.target_label
            persisted.append(existing)

        session.flush()
        return persisted

    def __repr__(self) -> str:
        return (
            f"GraphRegistry(id={self.id!r}, graph_name={self.graph_name!r}, "
            f"type={self.type.value if isinstance(self.type, SchemaType) else self.type!r}, "
            f"name={self.name!r})"
        )


__all__ = ["GraphSchemaRegistry", "SchemaType"]
