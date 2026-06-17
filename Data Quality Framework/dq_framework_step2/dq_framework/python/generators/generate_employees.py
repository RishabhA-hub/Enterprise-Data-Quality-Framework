"""
generate_employees.py
---------------------
Synthetic EMPLOYEE dataset with self-referential manager_id, plus
defects targeting DQ rules DQ005-DQ006.
"""

from __future__ import annotations

import csv
import os
from datetime import date, timedelta

import numpy as np
import yaml
from faker import Faker

from dq_framework.python.utils.corruption import (
    corrupt_date_format,
    corrupt_email,
    corrupt_numeric_range,
    inject_null,
    maybe_duplicate,
)

CONFIG_PATH = "dq_framework/config/generator_config.yaml"
RAW_OUT = "dq_framework/data/raw/employees_clean.csv"
COR_OUT = "dq_framework/data/corrupted/employees_corrupted.csv"

DEPARTMENTS = ["Sales", "Finance", "Engineering", "Marketing", "Operations", "HR"]


def _random_hire_date(rng: np.random.Generator) -> str:
    start = date(2010, 1, 1)
    span = (date(2025, 12, 31) - start).days
    return (start + timedelta(days=int(rng.integers(0, span)))).isoformat()


def generate(config: dict) -> tuple[list[dict], list[dict]]:
    fake = Faker()
    Faker.seed(config["seed"] + 1)
    rng = np.random.default_rng(config["seed"] + 1)

    n = config["volumes"]["employees"]
    c = config["corruption"]["employee"]

    clean_rows: list[dict] = []
    for i in range(1, n + 1):
        first = fake.first_name()
        last = fake.last_name()
        # First 10 employees are top-of-hierarchy (no manager)
        manager_id = None if i <= 10 else f"EMP{int(rng.integers(1, i)):05d}"
        clean_rows.append({
            "employee_id":  f"EMP{i:05d}",
            "first_name":   first,
            "last_name":    last,
            "email":        f"{first.lower()}.{last.lower()}@company.com",
            "department":   str(rng.choice(DEPARTMENTS)),
            "hire_date":    _random_hire_date(rng),
            "salary":       int(rng.integers(40000, 180000)),
            "manager_id":   manager_id,
        })

    corrupted_rows: list[dict] = []
    for row in clean_rows:
        r = dict(row)
        r["manager_id"] = inject_null(r["manager_id"], rng, c["null_manager_id"])
        r["hire_date"]  = corrupt_date_format(r["hire_date"], rng, c["bad_hire_date"])
        r["email"]      = corrupt_email(r["email"], rng, c["bad_email_format"])
        r["salary"]     = corrupt_numeric_range(r["salary"], rng, c["salary_out_of_range"])
        corrupted_rows.append(r)

    corrupted_rows = maybe_duplicate(corrupted_rows, rng, c["duplicate_rate"])
    return clean_rows, corrupted_rows


def _write(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    clean, corrupted = generate(config)
    _write(RAW_OUT, clean)
    _write(COR_OUT, corrupted)
    print(f"[employees] clean={len(clean):,}  corrupted={len(corrupted):,}")


if __name__ == "__main__":
    main()
