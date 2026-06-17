"""
corruption.py
-------------
Reusable data-corruption primitives used by the generators to inject
realistic, enterprise-style data-quality defects into otherwise clean
synthetic datasets.

Each function takes a single value (or a row/series) and a probability,
and returns a possibly-corrupted version. All functions are deterministic
when a seeded numpy.random.Generator is supplied, so test runs are
reproducible.

Defect taxonomy (mirrors the DQ rule families in STEP 1):
    - NULL injection           -> Completeness
    - Duplicate keys           -> Uniqueness
    - Format drift (dates,     -> Validity
      emails, phones, casing)
    - Referential breaks       -> Integrity
    - Out-of-range numerics    -> Accuracy / Business rules
    - Whitespace / encoding    -> Consistency
"""

from __future__ import annotations

import re
import string
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------
def inject_null(value, rng: np.random.Generator, prob: float = 0.05):
    """Replace value with None with the given probability."""
    if rng.random() < prob:
        return None
    return value


def inject_empty_string(value, rng: np.random.Generator, prob: float = 0.02):
    """Replace value with '' (empty string) -- a sneakier completeness defect
    than NULL because it bypasses naive IS NULL checks."""
    if rng.random() < prob:
        return ""
    return value


# ---------------------------------------------------------------------------
# Validity -- format drift
# ---------------------------------------------------------------------------
_DATE_FORMATS = [
    "%Y-%m-%d",      # ISO (canonical)
    "%d/%m/%Y",      # EU
    "%m/%d/%Y",      # US
    "%d-%b-%Y",      # 05-Jan-2025
    "%Y%m%d",        # compact
    "%d.%m.%Y",      # DE
]


def corrupt_date_format(iso_date: str, rng: np.random.Generator, prob: float = 0.15) -> str:
    """Re-format an ISO date string into a random non-ISO format."""
    if iso_date is None or iso_date == "":
        return iso_date
    if rng.random() >= prob:
        return iso_date
    from datetime import datetime
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
    except ValueError:
        return iso_date
    fmt = rng.choice([f for f in _DATE_FORMATS if f != "%Y-%m-%d"])
    return dt.strftime(fmt)


def corrupt_email(email: str, rng: np.random.Generator, prob: float = 0.08) -> str:
    """Inject realistic email defects: missing @, double dots, trailing
    whitespace, uppercase domain, or a stray comma instead of a dot."""
    if not email or rng.random() >= prob:
        return email
    mode = rng.integers(0, 5)
    if mode == 0:
        return email.replace("@", "")             # missing @
    if mode == 1:
        return email.replace(".", "..", 1)        # double dot
    if mode == 2:
        return f"  {email}  "                     # whitespace pad
    if mode == 3:
        return email.upper()                      # case drift
    return email.replace(".", ",", 1)             # comma typo


def corrupt_phone(phone: str, rng: np.random.Generator, prob: float = 0.10) -> str:
    """Strip formatting, add spaces, drop country code, etc."""
    if not phone or rng.random() >= prob:
        return phone
    digits = re.sub(r"\D", "", phone)
    mode = rng.integers(0, 4)
    if mode == 0:
        return digits                              # 5551234567
    if mode == 1:
        return " ".join([digits[i:i+3] for i in range(0, len(digits), 3)])
    if mode == 2 and len(digits) > 10:
        return digits[-10:]                        # drop country code
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def corrupt_casing(value: str, rng: np.random.Generator, prob: float = 0.05) -> str:
    """Random upper/lower/title casing drift for text columns."""
    if not value or rng.random() >= prob:
        return value
    mode = rng.integers(0, 3)
    return [value.upper(), value.lower(), value.title()][mode]


def add_whitespace(value: str, rng: np.random.Generator, prob: float = 0.05) -> str:
    """Pad with leading/trailing whitespace."""
    if not value or rng.random() >= prob:
        return value
    pad = " " * int(rng.integers(1, 4))
    return f"{pad}{value}{pad}"


# ---------------------------------------------------------------------------
# Accuracy / business rules
# ---------------------------------------------------------------------------
def corrupt_numeric_range(
    value: float,
    rng: np.random.Generator,
    prob: float = 0.03,
    negative: bool = True,
    extreme: bool = True,
) -> float:
    """Inject negative values or absurd magnitudes into a numeric column."""
    if value is None or rng.random() >= prob:
        return value
    if negative and rng.random() < 0.5:
        return -abs(value)
    if extreme:
        return value * float(rng.choice([1000, 10000, 100000]))
    return value


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------
def break_fk(fk_value, rng: np.random.Generator, prob: float = 0.04, pool: Optional[list] = None):
    """Replace a foreign-key value with one that does not exist in the
    parent table (orphan record)."""
    if rng.random() >= prob:
        return fk_value
    if pool:
        return rng.choice(pool)
    # Generic orphan: prefix with "ORPH-"
    return f"ORPH-{''.join(rng.choice(list(string.ascii_uppercase), size=6))}"


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------
def maybe_duplicate(rows: list, rng: np.random.Generator, dup_rate: float = 0.02) -> list:
    """Append exact duplicates of randomly sampled rows to the dataset."""
    if not rows or dup_rate <= 0:
        return rows
    n_dups = max(1, int(len(rows) * dup_rate))
    idx = rng.integers(0, len(rows), size=n_dups)
    dups = [dict(rows[i]) for i in idx]
    return rows + dups
