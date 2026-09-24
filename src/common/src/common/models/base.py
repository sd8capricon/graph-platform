from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""

    pass


class ApiOwnedBase(DeclarativeBase):
    """Declarative metadata for tables whose DDL is owned by the management API.

    Python services may map and access these shared tables, but must not create
    them through `Base.metadata.create_all()`.
    """

    pass


__all__ = ["ApiOwnedBase", "Base"]
