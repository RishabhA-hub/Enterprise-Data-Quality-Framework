# Quick Start Guide

## 5-Minute Setup

### Prerequisites
- PostgreSQL 16+ (local Docker or cloud instance)
- Python 3.11+
- Git

### Step 1: Clone & Setup
```bash
git clone <repository-url> dq-framework
cd dq-framework

# Create Python virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2: Configure Database
```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/dq_framework"
# Or create a .env file
```

### Step 3: Initialize Schema
```bash
psql $DATABASE_URL -f steps/01_foundation/01_dq_dimensions.sql
psql $DATABASE_URL -f steps/01_foundation/02_rule_catalog.sql
# ... continue through all migration files
```

Or use the automated bootstrap:
```bash
./scripts/bootstrap_db.sh
```

### Step 4: Run the Demo
```bash
./demo/run_e2e_demo.sh
```

Expected output:
```
[DEMO] Loading synthetic data...
[DEMO] Profiling 3 tables...
[DEMO] Executing 8 rules...
[DEMO] Reconciling orders...
[DEMO] Generating scorecard...
[DEMO] Exporting reports to ./demo/output/
[DEMO] Complete! Check ./demo/output/ for results.
```

### Step 5: View Results
```bash
# Scorecard
cat demo/output/scorecard.json

# Quarantine issues
psql $DATABASE_URL -c "SELECT * FROM quarantine_issues LIMIT 10;"

# Executive summary
psql $DATABASE_URL -c "SELECT * FROM v_executive_scorecard;"
```

---

## First Rule Authoring (10 minutes)

### Create a Custom Rule
```sql
-- Check that customer emails contain '@'
INSERT INTO rules (
    rule_name,
    rule_description,
    rule_type,
    severity,
    rule_sql,
    data_domain,
    dama_dimension
) VALUES (
    'customer_email_format',
    'Customer email must contain @ symbol',
    'SQL',
    'HIGH',
    'SELECT customer_id, email FROM customers WHERE email NOT LIKE ''%@%''',
    'crm',
    'VALIDITY'
);
```

### Execute the Rule
```python
from dq_engine import RuleEngine
engine = RuleEngine(database_url=os.environ['DATABASE_URL'])
result = engine.execute_rule('customer_email_format')
print(f"Failed: {result['failed_count']}, Passed: {result['passed_count']}")
```

### View in Scorecard
```sql
SELECT * FROM v_executive_scorecard WHERE data_domain = 'crm';
```

---

## Daily Operations

### Morning Health Check (2 minutes)
```bash
./scripts/health_check.sh
```

Checks:
- Database connectivity
- Open quarantine count
- Last execution timestamp
- Critical failure count

### Review Quarantine
```sql
SELECT 
    qi.issue_id,
    r.rule_name,
    qi.data_domain,
    qi.severity,
    qi.status,
    qi.created_at
FROM quarantine_issues qi
JOIN rules r ON qi.rule_id = r.rule_id
WHERE qi.status = 'OPEN'
ORDER BY 
    CASE qi.severity 
        WHEN 'CRITICAL' THEN 1 
        WHEN 'HIGH' THEN 2 
        WHEN 'MEDIUM' THEN 3 
        ELSE 4 
    END,
    qi.created_at DESC;
```

### Export Scorecard for Leadership
```bash
./scripts/export_scorecard.sh --format csv --output /tmp/scorecard_$(date +%Y%m%d).csv
```

---

## Troubleshooting

| Problem | Quick Fix |
|---|---|
| `connection refused` | Check PostgreSQL is running: `pg_isready` |
| `relation does not exist` | Run bootstrap: `./scripts/bootstrap_db.sh` |
| `permission denied` | Verify role has GRANT on schema: `\dn+` |
| Rule returns no rows | Check table exists and has data: `SELECT COUNT(*) FROM <table>` |
| Slow execution | Add index on filtered column: `CREATE INDEX ON <table>(<column>)` |

---

## Next Steps
1. Read `REFERENCE_ARCHITECTURE.md` for system design
2. Read `RUNBOOKS.md` for incident response
3. Read `governance_charter.md` for RBAC and SLAs
4. Customize `terraform/main.tf` for your cloud provider
5. Onboard your first data domain with 3-5 rules

---

## Support
- **Questions**: #data-quality Slack channel
- **Incidents**: Follow `RUNBOOKS.md`
- **Enhancements**: File GitHub issue with `enhancement` label
- **Security**: Report to security@company.com (do not file public issue)
