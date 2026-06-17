-- =====================================================================
-- Seed the rule repository with the 8 baseline rules from the spec.
-- Each rule_sql returns the COUNT of violating rows; the engine compares
-- it against records_checked to compute pass_rate_pct.
-- Add more rules later without code changes -> metadata-driven framework.
-- =====================================================================

INSERT INTO monitoring.dq_rules
    (rule_id, rule_name, target_table, target_column, dimension, severity, rule_sql, description)
VALUES
('DQ001','Customer_ID not null','staging.stg_customer','customer_id','Completeness','CRITICAL',
 'SELECT COUNT(*) FROM staging.stg_customer WHERE customer_id IS NULL OR customer_id = '''' ',
 'Every customer must have an ID.'),

('DQ002','Email format valid','staging.stg_customer','email','Validity','HIGH',
 'SELECT COUNT(*) FROM staging.stg_customer WHERE email IS NOT NULL AND email !~* ''^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$'' ',
 'Email must match RFC-like regex.'),

('DQ003','Revenue greater than zero','staging.stg_sales','revenue','Accuracy','HIGH',
 'SELECT COUNT(*) FROM staging.stg_sales WHERE revenue IS NULL OR revenue <= 0',
 'Negative or zero revenue is invalid.'),

('DQ004','Employee age between 18 and 65','staging.stg_employee','age','Accuracy','HIGH',
 'SELECT COUNT(*) FROM staging.stg_employee WHERE age IS NULL OR age < 18 OR age > 65',
 'Working-age bounds.'),

('DQ005','Joining date not in future','staging.stg_employee','joining_date','Validity','HIGH',
 'SELECT COUNT(*) FROM staging.stg_employee WHERE joining_date IS NULL OR joining_date::date > CURRENT_DATE',
 'Cannot join in the future.'),

('DQ006','Order date not null','staging.stg_sales','order_date','Completeness','CRITICAL',
 'SELECT COUNT(*) FROM staging.stg_sales WHERE order_date IS NULL OR order_date = '''' ',
 'Every order must have a date.'),

('DQ007','Customer IDs unique','staging.stg_customer','customer_id','Uniqueness','CRITICAL',
 'SELECT COALESCE(SUM(c)-COUNT(*),0) FROM (SELECT COUNT(*) c FROM staging.stg_customer WHERE customer_id IS NOT NULL GROUP BY customer_id HAVING COUNT(*)>1) d',
 'No duplicate customer_id.'),

('DQ008','State follows master list','staging.stg_customer','state','Consistency','MEDIUM',
 'SELECT COUNT(*) FROM staging.stg_customer c WHERE c.state IS NOT NULL AND UPPER(TRIM(c.state)) NOT IN (''MAHARASHTRA'',''KARNATAKA'',''UTTAR PRADESH'',''TAMIL NADU'',''DELHI'',''GUJARAT'',''WEST BENGAL'',''RAJASTHAN'')',
 'State value must standardize to master list.')
ON CONFLICT (rule_id) DO NOTHING;
