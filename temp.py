import os

import psycopg2
from dotenv import load_dotenv

from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

load_dotenv()


def get_pg_connection():
    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "postgres"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "postgres"),
    )
    return conn


def main():
    conn = get_pg_connection()
    repo = AgeGraphRepository(conn)
    exists = repo.graph_exists("f1_graph")
    print(exists)


if __name__ == "__main__":
    main()
