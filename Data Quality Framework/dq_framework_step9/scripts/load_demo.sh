#!/usr/bin/env bash
# ============================================================
# load_demo.sh — load CSVs into demo_src, then seed demo_tgt
# with an intentional ETL gap (~0.7% missing orders) so the
# reconciliation step has something to report.
# ============================================================
set -euo pipefail

: "${PGHOST:?PGHOST required}"
: "${PGUSER:?PGUSER required}"
: "${PGDATABASE:?PGDATABASE required}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ROOT/data"

echo ">> Applying demo schema ..."
psql -v ON_ERROR_STOP=1 -f "$ROOT/sql/20_demo_schema.sql"

echo ">> Truncating demo tables ..."
psql -v ON_ERROR_STOP=1 -c "
TRUNCATE demo_src.order_items, demo_src.orders,
         demo_src.products,    demo_src.customers,
         demo_tgt.fact_orders, demo_tgt.dim_customer RESTART IDENTITY;
"

echo ">> Copying CSVs into demo_src ..."
# customers has duplicate IDs at the tail (uniqueness defect demo) -> stage then dedup-insert
psql -v ON_ERROR_STOP=1 <<SQL
CREATE TEMP TABLE _stg_customers (LIKE demo_src.customers INCLUDING DEFAULTS);
ALTER TABLE _stg_customers DROP COLUMN loaded_at;
\\copy _stg_customers FROM '$DATA/customers.csv' WITH (FORMAT csv, HEADER true, NULL '');
-- keep the duplicates visible by inserting with ON CONFLICT DO NOTHING but
-- also stash them in a side table so quarantine can see them.
CREATE TABLE IF NOT EXISTS demo_src._dup_customers AS TABLE _stg_customers WITH NO DATA;
TRUNCATE demo_src._dup_customers;
WITH ins AS (
    INSERT INTO demo_src.customers
        (customer_id,email,full_name,country_code,signup_date,status)
    SELECT DISTINCT ON (customer_id)
        customer_id,email,full_name,country_code,signup_date,status
    FROM _stg_customers
    ORDER BY customer_id
    ON CONFLICT (customer_id) DO NOTHING
    RETURNING customer_id
)
INSERT INTO demo_src._dup_customers
SELECT s.* FROM _stg_customers s
LEFT JOIN ins i USING (customer_id)
WHERE i.customer_id IS NULL;

\\copy demo_src.products    FROM '$DATA/products.csv'    WITH (FORMAT csv, HEADER true, NULL '');
\\copy demo_src.orders      FROM '$DATA/orders.csv'      WITH (FORMAT csv, HEADER true, NULL '');
\\copy demo_src.order_items FROM '$DATA/order_items.csv' WITH (FORMAT csv, HEADER true, NULL '');
SQL

echo ">> Seeding demo_tgt warehouse (with intentional ETL gap) ..."
psql -v ON_ERROR_STOP=1 <<'SQL'
INSERT INTO demo_tgt.dim_customer
    (customer_id,email,full_name,country_code,signup_date,status)
SELECT customer_id,email,full_name,country_code,signup_date,status
FROM   demo_src.customers
ON CONFLICT (customer_id) DO NOTHING;

-- Intentionally drop ~0.7% of orders to create a reconciliation gap
INSERT INTO demo_tgt.fact_orders
    (order_id,customer_id,order_date,currency,total_amount,status)
SELECT order_id,customer_id,order_date,currency,total_amount,status
FROM   demo_src.orders
WHERE  random() > 0.007;
SQL

echo ">> Row counts:"
psql -v ON_ERROR_STOP=1 -c "
SELECT 'src.customers'   AS table, count(*) FROM demo_src.customers
UNION ALL SELECT 'src.products',     count(*) FROM demo_src.products
UNION ALL SELECT 'src.orders',       count(*) FROM demo_src.orders
UNION ALL SELECT 'src.order_items',  count(*) FROM demo_src.order_items
UNION ALL SELECT 'tgt.dim_customer', count(*) FROM demo_tgt.dim_customer
UNION ALL SELECT 'tgt.fact_orders',  count(*) FROM demo_tgt.fact_orders;
"
echo "Demo load complete."
