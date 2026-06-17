"""
generate_sales.py
-----------------
Synthetic SALES dataset (one row per order line). Depends on the previously
generated customer + employee files so it can produce realistic foreign
keys AND deliberate orphan records to exercise DQ rules DQ007-DQ008.
"""

from __future__ import annotations

import csv
import os
from datetime import date, timedelta

import numpy as np
import yaml

from dq_framework.python.utils.corruption import (
    break_fk,
    corrupt_date_format,
    corrupt_numeric_range,
    inject_null,
    maybe_duplicate,
)

CONFIG_PATH = "dq_framework/config/generator_config.yaml"
CUST_FILE = "dq_framework/data/raw/customers_clean.csv"
EMP_FILE = "dq_framework/data/raw/employees_clean.csv"
RAW_OUT = "dq_framework/data/raw/sales_clean.csv"
COR_OUT = "dq_framework/data/corrupted/sales_corrupted.csv"

PRODUCTS = [
    ("SKU-001", "Laptop Pro 14",    1899.00),
    ("SKU-002", "Wireless Mouse",     29.90),
    ("SKU-003", "4K Monitor 27\"",   549.00),
    ("SKU-004", "USB-C Hub",          79.00),
    ("SKU-005", "Mechanical KB",     159.00),
    ("SKU-006", "Webcam HD",          99.00),
    ("SKU-007", "Noise-Cancel HP",   349.00),
    ("SKU-008", "Standing Desk",     699.00),
]


def _load_ids(path: str, col: str) -> list[str]:
    with open(path, newline="", encoding="utf-8") as f:
        return [row[col] for row in csv.DictReader(f)]


def _random_order_date(rng: np.random.Generator) -> str:
    start = date(2023, 1, 1)
    span = (date(2025, 12, 31) - start).days
    return (start + timedelta(days=int(rng.integers(0, span)))).isoformat()


def generate(config: dict) -> tuple[list[dict], list[dict]]:
    rng = np.random.default_rng(config["seed"] + 2)
    n = config["volumes"]["sales"]
    c = config["corruption"]["sales"]

    customer_ids = _load_ids(CUST_FILE, "customer_id")
    employee_ids = _load_ids(EMP_FILE, "employee_id")

    clean_rows: list[dict] = []
    for i in range(1, n + 1):
        sku, name, unit_price = PRODUCTS[int(rng.integers(0, len(PRODUCTS)))]
        qty = int(rng.integers(1, 6))
        clean_rows.append({
            "order_id":     f"ORD{i:08d}",
            "order_date":   _random_order_date(rng),
            "customer_id":  str(rng.choice(customer_ids)),
            "employee_id":  str(rng.choice(employee_ids)),
            "product_sku":  sku,
            "product_name": name,
            "quantity":     qty,
            "unit_price":   unit_price,
            "amount":       round(qty * unit_price, 2),
            "currency":     "USD",
        })

    corrupted_rows: list[dict] = []
    for row in clean_rows:
        r = dict(row)
        r["customer_id"] = inject_null(r["customer_id"], rng, c["null_customer_id"])
        if r["customer_id"]:
            r["customer_id"] = break_fk(r["customer_id"], rng, c["orphan_customer"])
        r["employee_id"] = break_fk(r["employee_id"], rng, c["orphan_employee"])
        r["amount"]      = inject_null(r["amount"], rng, c["null_amount"])
        if r["amount"] is not None:
            r["amount"] = corrupt_numeric_range(
                r["amount"], rng,
                prob=c["negative_amount"] + c["extreme_amount"],
                negative=True, extreme=True,
            )
        r["order_date"] = corrupt_date_format(r["order_date"], rng, c["bad_order_date"])
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
    print(f"[sales] clean={len(clean):,}  corrupted={len(corrupted):,}")


if __name__ == "__main__":
    main()
