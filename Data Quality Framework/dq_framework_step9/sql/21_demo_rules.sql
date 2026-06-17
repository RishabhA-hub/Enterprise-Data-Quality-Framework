-- ============================================================
-- STEP 9: Seed rule catalog with demo-specific DQ rules.
-- These exercise every DAMA-DMBOK dimension implemented in Step 4.
-- Idempotent: safe to re-run.
-- ============================================================

INSERT INTO dq_rules
    (rule_name, dimension, severity, target_schema, target_table,
     rule_type, rule_sql, threshold_pct, enabled, description)
VALUES
('customers_email_completeness','COMPLETENESS','HIGH','demo_src','customers','SQL',
 'SELECT * FROM demo_src.customers WHERE email IS NULL OR email = '''' ',
 1.0, true, 'Customer email must be populated'),

('customers_email_validity','VALIDITY','MEDIUM','demo_src','customers','SQL',
 'SELECT * FROM demo_src.customers WHERE email IS NOT NULL AND email <> '''' AND email !~* ''^[^@\s]+@[^@\s]+\.[^@\s]+$'' ',
 1.0, true, 'Email must match RFC-ish pattern'),

('customers_uniqueness','UNIQUENESS','CRITICAL','demo_src','_dup_customers','SQL',
 'SELECT * FROM demo_src._dup_customers',
 0.0, true, 'Duplicate customer_id detected during load staging'),

('orders_currency_validity','VALIDITY','HIGH','demo_src','orders','SQL',
 'SELECT * FROM demo_src.orders WHERE currency NOT IN (''USD'',''EUR'',''GBP'',''JPY'')',
 0.5, true, 'Order currency must be in allowed ISO-4217 subset'),

('orders_future_dated','TIMELINESS','HIGH','demo_src','orders','SQL',
 'SELECT * FROM demo_src.orders WHERE order_date > now()',
 0.5, true, 'Orders should not be future-dated'),

('order_items_negative_qty','VALIDITY','HIGH','demo_src','order_items','SQL',
 'SELECT * FROM demo_src.order_items WHERE quantity <= 0',
 0.5, true, 'Order item quantity must be positive'),

('order_items_orphan','REFERENTIAL','CRITICAL','demo_src','order_items','SQL',
 'SELECT oi.* FROM demo_src.order_items oi LEFT JOIN demo_src.orders o ON o.order_id = oi.order_id WHERE o.order_id IS NULL',
 0.0, true, 'Every order_item must reference an existing order'),

('orders_total_consistency','CONSISTENCY','HIGH','demo_src','orders','SQL',
 'SELECT o.* FROM demo_src.orders o JOIN (SELECT order_id, SUM(line_amount) s FROM demo_src.order_items GROUP BY order_id) x USING (order_id) WHERE ABS(o.total_amount - x.s) > 0.01',
 2.0, true, 'orders.total_amount must equal SUM(order_items.line_amount)')

ON CONFLICT (rule_name) DO UPDATE SET
    rule_sql      = EXCLUDED.rule_sql,
    threshold_pct = EXCLUDED.threshold_pct,
    severity      = EXCLUDED.severity,
    enabled       = EXCLUDED.enabled,
    description   = EXCLUDED.description;

-- ETL reconciliation pair: source orders -> target fact_orders
INSERT INTO etl_recon_pairs
    (pair_name, source_schema, source_table, target_schema, target_table,
     key_columns, tolerance_pct, enabled)
VALUES
('orders_src_to_fact','demo_src','orders','demo_tgt','fact_orders',
 ARRAY['order_id'], 0.0, true)
ON CONFLICT (pair_name) DO UPDATE SET
    key_columns   = EXCLUDED.key_columns,
    tolerance_pct = EXCLUDED.tolerance_pct,
    enabled       = EXCLUDED.enabled;
