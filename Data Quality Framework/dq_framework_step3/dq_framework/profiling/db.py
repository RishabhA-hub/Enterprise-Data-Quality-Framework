"""Database connection helper for the DQ profiling engine."""
from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()


def get_conn():
    """Return a new psycopg2 connection driven by env vars."""
    return psycopg2.connect(
        host=os.getenv("DQ_PG_HOST", "localhost"),
        port=int(os.getenv("DQ_PG_PORT", "5432")),
        dbname=os.getenv("DQ_PG_DB", "dq_framework"),
        user=os.getenv("DQ_PG_USER", "postgres"),
        password=os.getenv("DQ_PG_PASSWORD", "postgres"),
    )


@contextmanager
def cursor(commit: bool = False):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
