# Step 2 — Synthetic Data + Controlled Corruption

## Goal
Produce realistic-looking enterprise data (Customers, Employees, Sales) with
**known, configurable defects** so the DQ engine in Step 3 has something
meaningful to detect, score, and report on.

## What gets generated

| Dataset    | Rows (default) | Clean file                          | Corrupted file (load into staging)         |
|------------|----------------|-------------------------------------|--------------------------------------------|
| Customers  | 5,000          | `data/raw/customers_clean.csv`      | `data/corrupted/customers_corrupted.csv`   |
| Employees  | 500            | `data/raw/employees_clean.csv`      | `data/corrupted/employees_corrupted.csv`   |
| Sales      | 20,000         | `data/raw/sales_clean.csv`          | `data/corrupted/sales_corrupted.csv`       |

The **clean** files are kept on disk so the ETL validation step can do a
true source-vs-target reconciliation later.

## Defect taxonomy

Every defect maps to a DQ dimension and to a baseline rule from Step 1.

| Dimension     | Defect injected                              | Example rule  |
|---------------|----------------------------------------------|---------------|
| Completeness  | NULLs, empty strings in required columns     | DQ001, DQ005  |
| Validity      | Wrong date formats, malformed emails/phones  | DQ002, DQ006  |
| Uniqueness    | Duplicated primary keys                      | DQ003         |
| Integrity     | Orphan foreign keys (customer/employee)      | DQ007, DQ008  |
| Accuracy      | Negative or absurdly large monetary amounts  | DQ004         |
| Consistency   | Case drift, whitespace padding               | (cross-rule)  |

All probabilities are centralised in `config/generator_config.yaml` so you
can toggle a "clean run" (set everything to 0) vs. a "stressed run".

## Reproducibility
Every generator uses a seeded `numpy.random.Generator` and `Faker.seed(...)`.
Same `seed` in the config -> byte-identical CSV output.

## How to run

```bash
# from the project root (the folder that *contains* dq_framework/)
pip install -r dq_framework/requirements.txt
python -m dq_framework.python.generate_all
```

Output:

```
============================================================
DQ Framework -- Step 2: Synthetic Data Generation
============================================================
[customers] clean=5,000   corrupted=5,100
[employees] clean=500     corrupted=505
[sales]     clean=20,000  corrupted=20,300
```

## Loading into the staging schema (Step 1)

```sql
\copy staging.stg_customer(customer_id, first_name, last_name, email, phone, country, signup_date)
  FROM 'dq_framework/data/corrupted/customers_corrupted.csv' CSV HEADER;

\copy staging.stg_employee(employee_id, first_name, last_name, email, department, hire_date, salary, manager_id)
  FROM 'dq_framework/data/corrupted/employees_corrupted.csv' CSV HEADER;

\copy staging.stg_sales(order_id, order_date, customer_id, employee_id, product_sku, product_name, quantity, unit_price, amount, currency)
  FROM 'dq_framework/data/corrupted/sales_corrupted.csv' CSV HEADER;
```

> The staging tables use `TEXT` for dates / emails / phones on purpose —
> that's what lets the malformed values survive long enough for the DQ
> engine to flag them in Step 3.

## Next
**Step 3** will implement the rule-driven DQ engine that scans these
staging tables, executes every row in `monitoring.dq_rules`, populates
`dq_rule_results` + `dq_quality_scores`, and emits a run-level report.
