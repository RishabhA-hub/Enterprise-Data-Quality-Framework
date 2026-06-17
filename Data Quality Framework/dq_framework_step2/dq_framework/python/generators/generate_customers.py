"""
generate_customers.py
---------------------
Produces a synthetic CUSTOMER dataset and writes it to:

    data/raw/customers_clean.csv          (pristine, for diffing)
    data/corrupted/customers_corrupted.csv (loaded into stg_customer)

Defects injected map directly to DQ rules DQ001-DQ004 from STEP 1.
"""

from __future__ import annotations

import csv
import os
from datetime import date, timedelta

import numpy as np
import yaml
from faker import Faker

from dq_framework.python.utils.corruption import (
    add_whitespace,
    corrupt_casing,
    corrupt_date_format,
    corrupt_email,
    corrupt_phone,
    inject_empty_string,
    inject_null,
    maybe_duplicate,
)

CONFIG_PATH = "dq_framework/config/generator_config.yaml"
RAW_OUT = "dq_framework/data/raw/customers_clean.csv"
COR_OUT = "dq_framework/data/corrupted/customers_corrupted.csv"


def _random_signup_date(rng: np.random.Generator) -> str:
    start = date(2018, 1, 1)
    span = (date(2025, 12, 31) - start).days
    return (start + timedelta(days=int(rng.integers(0, span)))).isoformat()


def generate(config: dict) -> tuple[list[dict], list[dict]]:
    fake = Faker()
    Faker.seed(config["seed"])
    rng = np.random.default_rng(config["seed"])

    n = config["volumes"]["customers"]
    c = config["corruption"]["customer"]

    clean_rows: list[dict] = []
    for i in range(1, n + 1):
        first = fake.first_name()
        last = fake.last_name()
        clean_rows.append({
            "customer_id":  f"CUST{i:06d}",
            "first_name":   first,
            "last_name":    last,
            "email":        f"{first.lower()}.{last.lower()}@{fake.free_email_domain()}",
            "phone":        fake.numerify("+1-###-###-####"),
            "country":      fake.country_code(),
            "signup_date":  _random_signup_date(rng),
        })

    corrupted_rows: list[dict] = []
    for row in clean_rows:
        r = dict(row)
        r["email"]       = inject_null(r["email"], rng, c["null_email"])
        r["email"]       = corrupt_email(r["email"], rng, c["bad_email_format"]) if r["email"] else r["email"]
        r["phone"]       = inject_null(r["phone"], rng, c["null_phone"])
        r["phone"]       = corrupt_phone(r["phone"], rng, c["bad_phone_format"]) if r["phone"] else r["phone"]
        r["signup_date"] = corrupt_date_format(r["signup_date"], rng, c["bad_signup_date"])
        r["first_name"]  = corrupt_casing(r["first_name"], rng, c["casing_drift"])
        r["last_name"]   = add_whitespace(r["last_name"], rng, c["whitespace_pad"])
        r["country"]     = inject_empty_string(r["country"], rng, 0.02)
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
    print(f"[customers] clean={len(clean):,}  corrupted={len(corrupted):,}")


if __name__ == "__main__":
    main()
