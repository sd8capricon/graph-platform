import os

from psycopg import AsyncConnection


def database_url() -> str:
    """Build the SQLAlchemy async database URL from the environment.

    Reads `PGUSER`, `PGPASSWORD`, `PGHOST`, `PGPORT` and `PGDATABASE` - the same
    variables `create_connection()` uses - and renders them as a
    `postgresql+psycopg://` URL for `create_async_engine()`.

    Returns:
        The SQLAlchemy async connection string.
    """
    return (
        f"postgresql+psycopg://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}"
        f"@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
    )


async def create_connection() -> AsyncConnection:
    """Open a psycopg async connection with the Apache Age setup statements run.

    Runs `CREATE EXTENSION IF NOT EXISTS age;` (which creates the `ag_catalog`
    schema and tables - `LOAD 'age'` alone only loads the shared library into the
    session and leaves `ag_catalog.ag_graph` undefined), then `LOAD 'age';` unless
    the host is Azure-hosted (there the extension is pre-loaded via server
    config; detectable by `"database.azure.com" in host`), then
    `CREATE EXTENSION IF NOT EXISTS vector;`, then
    `SET search_path = ag_catalog, "$user", public;` - required because AGE's own
    DDL resolves operator classes through `search_path`, not schema-qualification.

    Commits before returning: the connection defaults to non-autocommit, and a
    later SQLAlchemy connection that runs `Base.metadata.create_all` cannot see an
    uncommitted `CREATE EXTENSION vector` under Postgres MVCC.

    Returns:
        An open, committed `psycopg.AsyncConnection` with Age ready to use.
    """
    host = os.environ["PGHOST"]
    connection = await AsyncConnection.connect(
        host=host,
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )
    async with connection.cursor() as cursor:
        await cursor.execute("CREATE EXTENSION IF NOT EXISTS age;")
        # Azure Postgres has AGE pre-loaded via server config; skip LOAD for Azure hosts
        is_azure = "database.azure.com" in host
        if not is_azure:
            await cursor.execute("LOAD 'age';")
        await cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        await cursor.execute('SET search_path = ag_catalog, "$user", public;')
    await connection.commit()
    return connection


__all__ = ["create_connection", "database_url"]
