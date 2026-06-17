"""
Data Profiling Engine
=====================

Computes column-level statistics for any staging table:
  - row count
  - null count + null %
  - distinct count + distinct %
  - min / max / mean / stddev (numeric)
  - min / max length (text)
  - top-N most frequent values
  - pattern inference (regex bucket) for text
  - inferred semantic type (email, phone, date, integer, decimal, text)

Output: pandas DataFrame + optional persistence to monitoring.dq_profile_results.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

import pandas as pd

from db import cursor

# ---------------------------------------------------------------------------
# Regex library for semantic type inference
# ---------------------------------------------------------------------------
PATTERNS = {
    "email":    re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"),
    "phone_e164": re.compile(r"^\+?[1-9]\d{7,14}$"),
    "phone_us": re.compile(r"^\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}$"),
    "date_iso": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "date_us":  re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$"),
    "integer":  re.compile(r"^-?\d+$"),
    "decimal":  re.compile(r"^-?\d+\.\d+$"),
    "uuid":     re.compile(r"^[0-9a-fA-F-]{36}$"),
}


def infer_semantic_type(values: list[str]) -> str:
    """Return the dominant semantic type for a sample of non-null string values."""
    if not values:
        return "unknown"
    counts: dict[str, int] = {k: 0 for k in PATTERNS}
    for v in values:
        s = str(v).strip()
        for name, rx in PATTERNS.items():
            if rx.match(s):
                counts[name] += 1
                break
    winner = max(counts, key=counts.get)
    return winner if counts[winner] / len(values) >= 0.6 else "text"


# ---------------------------------------------------------------------------
# Column profile dataclass
# ---------------------------------------------------------------------------
@dataclass
class ColumnProfile:
    schema_name: str
    table_name: str
    column_name: str
    data_type: str
    inferred_type: str
    row_count: int
    null_count: int
    null_pct: float
    distinct_count: int
    distinct_pct: float
    min_value: Any
    max_value: Any
    mean_value: float | None
    stddev_value: float | None
    min_length: int | None
    max_length: int | None
    top_values: str  # JSON-ish "v1:cnt|v2:cnt|..."


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------
def list_columns(schema: str, table: str) -> list[tuple[str, str]]:
    sql = """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """
    with cursor() as cur:
        cur.execute(sql, (schema, table))
        return [(r["column_name"], r["data_type"]) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Profiling logic
# ---------------------------------------------------------------------------
def profile_column(schema: str, table: str, column: str, dtype: str,
                   top_n: int = 5, sample_size: int = 500) -> ColumnProfile:
    fq = f'"{schema}"."{table}"'
    col = f'"{column}"'

    with cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM {fq}")
        row_count = cur.fetchone()["c"]

        cur.execute(f"SELECT COUNT(*) AS c FROM {fq} WHERE {col} IS NULL")
        null_count = cur.fetchone()["c"]

        cur.execute(f"SELECT COUNT(DISTINCT {col}) AS c FROM {fq}")
        distinct_count = cur.fetchone()["c"]

        min_v = max_v = mean_v = stddev_v = None
        min_len = max_len = None

        numeric_types = ("integer", "bigint", "numeric", "double precision", "real", "smallint")
        if dtype in numeric_types:
            cur.execute(
                f"SELECT MIN({col})::text mn, MAX({col})::text mx, "
                f"AVG({col})::float mean, STDDEV({col})::float sd FROM {fq}"
            )
            r = cur.fetchone()
            min_v, max_v, mean_v, stddev_v = r["mn"], r["mx"], r["mean"], r["sd"]
        else:
            cur.execute(
                f"SELECT MIN({col})::text mn, MAX({col})::text mx, "
                f"MIN(LENGTH({col}::text)) mnl, MAX(LENGTH({col}::text)) mxl FROM {fq}"
            )
            r = cur.fetchone()
            min_v, max_v, min_len, max_len = r["mn"], r["mx"], r["mnl"], r["mxl"]

        cur.execute(
            f"SELECT {col}::text AS v, COUNT(*) AS c FROM {fq} "
            f"WHERE {col} IS NOT NULL GROUP BY {col} ORDER BY c DESC LIMIT %s",
            (top_n,),
        )
        top = cur.fetchall()
        top_values = "|".join(f"{row['v']}:{row['c']}" for row in top)

        cur.execute(
            f"SELECT {col}::text AS v FROM {fq} WHERE {col} IS NOT NULL LIMIT %s",
            (sample_size,),
        )
        sample = [r["v"] for r in cur.fetchall()]
        inferred = infer_semantic_type(sample)

    null_pct = (null_count / row_count * 100) if row_count else 0.0
    distinct_pct = (distinct_count / row_count * 100) if row_count else 0.0

    return ColumnProfile(
        schema_name=schema, table_name=table, column_name=column,
        data_type=dtype, inferred_type=inferred,
        row_count=row_count, null_count=null_count, null_pct=round(null_pct, 2),
        distinct_count=distinct_count, distinct_pct=round(distinct_pct, 2),
        min_value=min_v, max_value=max_v,
        mean_value=mean_v, stddev_value=stddev_v,
        min_length=min_len, max_length=max_len,
        top_values=top_values,
    )


def profile_table(schema: str, table: str) -> pd.DataFrame:
    """Profile every column of `schema.table` and return a DataFrame."""
    cols = list_columns(schema, table)
    if not cols:
        raise ValueError(f"No columns found for {schema}.{table}")
    rows = [asdict(profile_column(schema, table, c, dt)) for c, dt in cols]
    return pd.DataFrame(rows)


def persist_profile(df: pd.DataFrame, execution_id: int) -> None:
    """Write the profile DataFrame to monitoring.dq_profile_results."""
    insert_sql = """
        INSERT INTO monitoring.dq_profile_results
            (execution_id, schema_name, table_name, column_name, data_type,
             inferred_type, row_count, null_count, null_pct, distinct_count,
             distinct_pct, min_value, max_value, mean_value, stddev_value,
             min_length, max_length, top_values)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    with cursor(commit=True) as cur:
        for _, r in df.iterrows():
            cur.execute(insert_sql, (
                execution_id, r.schema_name, r.table_name, r.column_name,
                r.data_type, r.inferred_type, r.row_count, r.null_count,
                r.null_pct, r.distinct_count, r.distinct_pct,
                str(r.min_value) if r.min_value is not None else None,
                str(r.max_value) if r.max_value is not None else None,
                r.mean_value, r.stddev_value, r.min_length, r.max_length,
                r.top_values,
            ))
