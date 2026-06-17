-- ---------------------------------------------------------------------------
-- Seed: baseline ETL reconciliation jobs (staging -> clean)
-- Each job's source_sql and target_sql MUST each return a single scalar.
-- ---------------------------------------------------------------------------

INSERT INTO monitoring.etl_validation_jobs
    (job_name, check_type, source_sql, target_sql, tolerance_pct, description)
VALUES
-- ---------- CUSTOMERS ----------
('cust_rowcount', 'row_count',
 $$SELECT COUNT(*) FROM staging.stg_customer
     WHERE customer_id IS NOT NULL AND email ~ '^[^@]+@[^@]+\.[^@]+$'$$,
 $$SELECT COUNT(*) FROM clean.dim_customer WHERE is_current = TRUE$$,
 0.5, 'Valid staging customers == current dim rows'),

('cust_distinct_bk', 'distinct_check',
 $$SELECT COUNT(DISTINCT customer_id) FROM staging.stg_customer
     WHERE customer_id IS NOT NULL$$,
 $$SELECT COUNT(DISTINCT customer_bk) FROM clean.dim_customer$$,
 0, 'Distinct business keys match'),

-- ---------- EMPLOYEES ----------
('emp_rowcount', 'row_count',
 $$SELECT COUNT(*) FROM staging.stg_employee WHERE employee_id IS NOT NULL$$,
 $$SELECT COUNT(*) FROM clean.dim_employee WHERE is_current = TRUE$$,
 0.5, 'Valid staging employees == current dim rows'),

-- ---------- SALES ----------
('sales_rowcount', 'row_count',
 $$SELECT COUNT(*) FROM staging.stg_sales
     WHERE order_id IS NOT NULL
       AND customer_id IN (SELECT customer_id FROM staging.stg_customer)$$,
 $$SELECT COUNT(*) FROM clean.fact_sales$$,
 0.5, 'Valid staging sales == fact rows'),

('sales_amount_sum', 'sum_check',
 $$SELECT COALESCE(SUM(amount::numeric),0) FROM staging.stg_sales
     WHERE amount ~ '^-?[0-9]+(\.[0-9]+)?$'
       AND order_id IS NOT NULL$$,
 $$SELECT COALESCE(SUM(amount),0) FROM clean.fact_sales$$,
 0.01, 'Revenue totals reconcile within 0.01%'),

('sales_qty_sum', 'sum_check',
 $$SELECT COALESCE(SUM(quantity::int),0) FROM staging.stg_sales
     WHERE quantity ~ '^-?[0-9]+$' AND order_id IS NOT NULL$$,
 $$SELECT COALESCE(SUM(quantity),0) FROM clean.fact_sales$$,
 0, 'Quantity totals exact match'),

('sales_distinct_orders', 'distinct_check',
 $$SELECT COUNT(DISTINCT order_id) FROM staging.stg_sales
     WHERE order_id IS NOT NULL$$,
 $$SELECT COUNT(DISTINCT order_bk) FROM clean.fact_sales$$,
 0, 'Distinct order business keys match'),

('sales_orphan_customers', 'orphan_check',
 $$SELECT 0$$,
 $$SELECT COUNT(*) FROM clean.fact_sales f
     LEFT JOIN clean.dim_customer d ON d.customer_sk = f.customer_sk
    WHERE d.customer_sk IS NULL$$,
 0, 'Zero fact rows orphaned from dim_customer'),

('sales_orphan_employees', 'orphan_check',
 $$SELECT 0$$,
 $$SELECT COUNT(*) FROM clean.fact_sales f
     LEFT JOIN clean.dim_employee d ON d.employee_sk = f.employee_sk
    WHERE d.employee_sk IS NULL$$,
 0, 'Zero fact rows orphaned from dim_employee')
ON CONFLICT (job_name) DO NOTHING;
