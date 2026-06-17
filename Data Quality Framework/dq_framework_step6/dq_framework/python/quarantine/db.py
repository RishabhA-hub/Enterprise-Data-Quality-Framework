"""Postgres connection helper (shared across steps)."""
import os, psycopg2
from psycopg2.extras import RealDictCursor, Json
from dotenv import load_dotenv
load_dotenv()


def get_conn():
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "dq_framework"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "postgres"),
    )


def dict_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor)
