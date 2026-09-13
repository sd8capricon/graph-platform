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

    A model identifier (`openai/text-embedding-3-small`) is not a valid SQL
    identifier, so it is slugified rather than quoted through: the width is
    appended so the name still reads as the thing it indexes.

    Args:
        table_name: The table the index is built on.
        model: The embedding provider configuration being indexed.

    Returns:
        An identifier-safe index name.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", model.identifier.lower()).strip("_")
    return f"ix_{table_name}_emb_{slug}_{model.embedding_dimension}"


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

        CREATE INDEX IF NOT EXISTS "ix_node_embedding_emb_openai_..._1536"
          ON "node_embedding" USING hnsw ((embedding::vector(1536)) vector_cosine_ops)
          WHERE embedding_model = 'openai/text-embedding-3-small'

    This is why `vector_search()` on both models always filters by
    `model.identifier` *and* orders by the same `::vector(n)` cast: a partial
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
            `identifier` becomes the index predicate and its `embedding_dimension`
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
            "WHERE embedding_model = {model}"
        )
        .format(
            name=sql.Identifier(_index_name(table_name, model)),
            table=sql.Identifier(table_name),
            dimension=sql.Literal(model.embedding_dimension),
            model=sql.Literal(model.identifier),
        )
        .as_string(None)
    )

    await session.execute(text(statement))
    return statement


__all__ = ["HNSW_MAX_DIMENSIONS", "ensure_embedding_index"]
