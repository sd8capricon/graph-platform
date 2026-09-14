"""Model-agnostic DDL helpers for per-model pgvector ANN indexes.

Both embedding tables store a **dimensionless** `vector` column (ADR-0003) so
organizations on different embedding models can share one table (ADR-0002). A
dimensionless column cannot be ANN-indexed directly, so each embedding model
gets its own partial expression index instead - one index per model, not per
organization. Nothing here knows about any ORM model: the caller passes the
`table_name` it wants indexed and the `Model` whose rows the index covers, which
is what lets both `NodeEmbedding` and `SchemaEmbedding` delegate through their
own `ensure_embedding_index()` / `drop_embedding_index()` classmethods.

The `Model` -> litellm mapping lives in `services/embedding_service.py`; the
`Model` shape itself lives in `schemas/model.py`.
"""

import re

from psycopg import sql
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from graphrag_apacheage.schemas.model import Model

HNSW_MAX_DIMENSIONS = 2000
"""Largest vector width pgvector's HNSW index supports for the `vector` type.

A model wider than this (e.g. OpenAI's `text-embedding-3-large`, 3072) still works
end to end - it simply cannot be given an HNSW index on a `vector` column, so its
searches fall back to a sequential scan. Indexing one would mean storing it as
`halfvec` (supported up to 4000) instead, which is a larger change than
ADR-0003 makes.
"""


def _index_name(table_name: str, model: Model) -> str:
    """Build a deterministic, injection-safe index name for a table/model pair.

    A model id is caller-assigned and not necessarily a valid (or short) SQL
    identifier, so it is slugified rather than quoted through, and bounded to
    32 characters: PostgreSQL identifiers are limited to 63 bytes, and a UUID
    id alone slugifies to 36 - past that limit once the table name, prefix, and
    dimension are added. The dimension is still appended so the name reads as
    the thing it indexes.

    Args:
        table_name: The table the index is built on.
        model: The embedding provider configuration being indexed.

    Returns:
        An identifier-safe index name.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", model.id.lower()).strip("_")[:32]
    return f"ix_{table_name}_emb_{slug}_{model.embedding_dimension}"


async def drop_embedding_index(
    session: AsyncSession, table_name: str, model: Model
) -> str:
    """Drop one embedding model's partial HNSW index on a table, if present.

    The inverse of :func:`ensure_embedding_index`: emits

        DROP INDEX IF EXISTS "ix_<table>_emb_<id-slug>_<dimension>"

    using the exact same deterministic name `_index_name()` derives, so a paired
    ensure/drop round-trip is idempotent on both sides and always refers to the
    same physical index.

    `IF EXISTS` is what makes the "drop what we *may* have created" contract
    cheap and safe to run unconditionally (e.g. when tearing a model out of
    config), the way `IF NOT EXISTS` makes `ensure_embedding_index()` safe to
    run on every startup - no catalog lookup for the existence check, no error
    when the model was never indexed.

    The validation mirrors `ensure_embedding_index()` exactly, even though the
    emitted DDL needs only the name: a model that could never be indexed (no
    `embedding_dimension`, or wider than `HNSW_MAX_DIMENSIONS`) has, by
    definition, no index to drop, and the two functions must agree on when the
    `_index_name()` render is even well-defined. Keeping the same guard documents
    the pair and refuses the internal-inconsistency case where one half of the
    pair would no-op on a name the other half cannot even produce.

    Args:
        session: SQLAlchemy async session used to execute the DDL. Must be bound
            to PostgreSQL, like :func:`ensure_embedding_index`.
        table_name: The table whose index to drop (`node_embedding` /
            `schema_embedding`).
        model: The embedding provider configuration whose rows the index covered.
            Its `id` and `embedding_dimension` select the same index
            `ensure_embedding_index()` would have created.

    Returns:
        The `DROP INDEX` statement that was executed.

    Raises:
        ValueError: If `model` has no `embedding_dimension`, or that dimension
            exceeds `HNSW_MAX_DIMENSIONS` - in which case no statement was
            executed and no index for that model can exist.
    """
    if model.embedding_dimension is None:
        raise ValueError(
            f"{model.identifier} has no embedding_dimension; it is not an "
            "embedding model and has no vectors to index"
        )
    if model.embedding_dimension > HNSW_MAX_DIMENSIONS:
        raise ValueError(
            f"{model.identifier} is {model.embedding_dimension}-dimensional, above "
            f"pgvector's HNSW limit of {HNSW_MAX_DIMENSIONS} for the 'vector' type. "
            "Such a model was never given an index, so there is nothing to drop."
        )

    statement = (
        sql.SQL("DROP INDEX IF EXISTS {name}")
        .format(name=sql.Identifier(_index_name(table_name, model)))
        .as_string(None)
    )

    await session.execute(text(statement))
    return statement


async def ensure_embedding_index(
    session: AsyncSession, table_name: str, model: Model
) -> str:
    """Create a table's partial HNSW index for one embedding model, if absent.

    Both embedding tables store a **dimensionless** `vector` column (ADR-0003) so
    that organizations on different embedding models - and therefore different
    vector widths - can share one table. pgvector cannot index such a column
    directly; its documented workaround for exactly this case is an *expression*
    index that casts to a fixed width, made *partial* so it only covers the rows
    actually of that width:

        CREATE INDEX IF NOT EXISTS "ix_node_embedding_emb_<id-slug>_1536"
          ON "node_embedding" USING hnsw ((embedding::vector(1536)) vector_cosine_ops)
          WHERE embedding_model_id = '<model.id>'

    This is why `vector_search()` on both models always filters by
    `model.id` *and* orders by the same `::vector(n)` cast: a partial
    index is only usable when the query carries its predicate, and an expression
    index only when the query repeats its expression. The two are a matched pair -
    changing one without the other silently drops back to a sequential scan.

    One index exists per embedding model rather than per organization: the count
    is then bounded by how many providers the deployment supports, not by how many
    tenants it has.

    Not `CONCURRENTLY`: that cannot run inside a transaction, and the natural time
    to call this is when a model is first configured, before it has any rows. To
    add an index to an already-large table, run the returned statement with
    `CONCURRENTLY` on a separate autocommit connection instead.

    Args:
        session: SQLAlchemy async session used to execute the DDL. Must be bound
            to PostgreSQL - the `vector` type and HNSW are PostgreSQL-only.
        table_name: The table to index (`node_embedding` / `schema_embedding`).
        model: The embedding provider configuration whose rows to index. Its
            `id` becomes the index predicate and its `embedding_dimension`
            the cast width.

    Returns:
        The `CREATE INDEX` statement that was executed.

    Raises:
        ValueError: If `model` has no `embedding_dimension` (it is not an
            embedding model), or if that dimension exceeds `HNSW_MAX_DIMENSIONS`.
    """
    if model.embedding_dimension is None:
        raise ValueError(
            f"{model.identifier} has no embedding_dimension; it is not an "
            "embedding model and has no vectors to index"
        )
    if model.embedding_dimension > HNSW_MAX_DIMENSIONS:
        raise ValueError(
            f"{model.identifier} is {model.embedding_dimension}-dimensional, above "
            f"pgvector's HNSW limit of {HNSW_MAX_DIMENSIONS} for the 'vector' type. "
            "Its searches work but fall back to a sequential scan; indexing it "
            "would require storing the column as 'halfvec' instead."
        )

    statement = (
        sql.SQL(
            "CREATE INDEX IF NOT EXISTS {name} ON {table} "
            "USING hnsw ((embedding::vector({dimension})) vector_cosine_ops) "
            "WHERE embedding_model_id = {model}"
        )
        .format(
            name=sql.Identifier(_index_name(table_name, model)),
            table=sql.Identifier(table_name),
            dimension=sql.Literal(model.embedding_dimension),
            model=sql.Literal(model.id),
        )
        .as_string(None)
    )

    await session.execute(text(statement))
    return statement


__all__ = ["HNSW_MAX_DIMENSIONS", "drop_embedding_index", "ensure_embedding_index"]
