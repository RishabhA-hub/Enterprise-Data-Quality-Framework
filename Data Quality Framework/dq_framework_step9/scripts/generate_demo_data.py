"""
generate_demo_data.py
---------------------
Synthesises a realistic retail dataset with INTENTIONAL data-quality
defects so the DQ framework has something meaningful to detect.

Defect catalogue injected (by design):
  * NULL emails on ~3% of customers      -> completeness rule fires
  * Malformed emails on ~2%              -> validity rule fires
  * Duplicate customer_id (rare)         -> uniqueness rule fires
  * Negative quantities                  -> validity / business rule
  * Order total != sum(line_amount)      -> consistency rule
  * Orphan order_items (missing parent)  -> referential rule
  * Future-dated orders                  -> timeliness rule
  * Currency outside allowed set         -> validity rule
  * Source rows missing in target        -> ETL reconciliation gap

Outputs CSVs into ./data/ ready for COPY into demo_src.* tables.
"""
from __future__ import annotations
import csv, os, random, string
from datetime import datetime, timedelta, timezone
from pathlib import Path

random.seed(42)
OUT = Path(__file__).resolve().parent.parent / "data"
OUT.mkdir(parents=True, exist_ok=True)

N_CUSTOMERS = 5_000
N_PRODUCTS  = 250
N_ORDERS    = 12_000
AVG_ITEMS   = 2.4

COUNTRIES = ["US", "GB", "DE", "FR", "IN", "BR", "JP", "AU", "CA", "ZA"]
CURRENCIES_VALID = ["USD", "EUR", "GBP", "JPY"]
STATUSES = ["NEW", "PAID", "SHIPPED", "DELIVERED", "CANCELLED"]


def rand_email(name: str, broken: bool = False) -> str:
    user = name.lower().replace(" ", ".")
    if broken:
        # Deliberately invalid forms
        return random.choice([f"{user}@", f"{user}", f"{user}@@x.com", f"{user}.com"])
    domain = random.choice(["acme.io", "globex.com", "initech.co", "umbrella.org"])
    return f"{user}@{domain}"


def rand_name() -> str:
    first = random.choice(["Alex","Sam","Priya","Wei","Lars","Maria","Kenji","Aisha","Diego","Nora"])
    last  = random.choice(["Khan","Smith","Garcia","Tanaka","Mueller","Silva","Dubois","Patel","Cohen","Okafor"])
    return f"{first} {last}"


# ---------- customers ----------
print("Generating customers ...")
customers = []
with (OUT / "customers.csv").open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["customer_id","email","full_name","country_code","signup_date","status"])
    for cid in range(1, N_CUSTOMERS + 1):
        name = rand_name()
        # defect injection
        roll = random.random()
        if roll < 0.03:
            email = ""                                  # NULL completeness defect
        elif roll < 0.05:
            email = rand_email(name, broken=True)       # validity defect
        else:
            email = rand_email(name)
        signup = datetime(2022,1,1) + timedelta(days=random.randint(0, 1400))
        status = random.choices(["ACTIVE","CHURNED","SUSPENDED"], weights=[0.85,0.12,0.03])[0]
        w.writerow([cid, email, name, random.choice(COUNTRIES), signup.date().isoformat(), status])
        customers.append(cid)
    # uniqueness defect: re-emit 5 duplicate IDs at the tail
    for cid in random.sample(customers, 5):
        w.writerow([cid, rand_email(rand_name()), rand_name(), "US",
                    datetime(2024,1,1).date().isoformat(), "ACTIVE"])

# ---------- products ----------
print("Generating products ...")
products = []
with (OUT / "products.csv").open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["product_id","sku","name","category","unit_price","active"])
    for pid in range(1, N_PRODUCTS + 1):
        sku = "SKU-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        cat = random.choice(["Electronics","Apparel","Home","Grocery","Sports","Books"])
        price = round(random.uniform(2.5, 999.0), 2)
        w.writerow([pid, sku, f"Product {pid}", cat, price, random.random() > 0.05])
        products.append((pid, price))

# ---------- orders + items ----------
print("Generating orders & items ...")
now = datetime.now(timezone.utc)
with (OUT / "orders.csv").open("w", newline="") as fo, \
     (OUT / "order_items.csv").open("w", newline="") as fi:
    wo = csv.writer(fo); wi = csv.writer(fi)
    wo.writerow(["order_id","customer_id","order_date","currency","total_amount","status"])
    wi.writerow(["order_item_id","order_id","product_id","quantity","unit_price","line_amount"])
    item_id = 0
    for oid in range(1, N_ORDERS + 1):
        cust = random.choice(customers)
        # timeliness defect: ~0.5% future-dated
        if random.random() < 0.005:
            odate = now + timedelta(days=random.randint(5, 60))
        else:
            odate = now - timedelta(days=random.randint(0, 720),
                                    hours=random.randint(0,23))
        # validity defect: ~0.4% bad currency
        currency = "ZZZ" if random.random() < 0.004 else random.choice(CURRENCIES_VALID)
        n_items = max(1, int(random.gauss(AVG_ITEMS, 1.2)))
        line_total = 0.0
        lines = []
        for _ in range(n_items):
            item_id += 1
            pid, price = random.choice(products)
            qty = random.randint(1, 6)
            # validity defect: ~0.3% negative qty
            if random.random() < 0.003:
                qty = -qty
            line_amt = round(qty * price, 2)
            line_total += line_amt
            lines.append((item_id, oid, pid, qty, price, line_amt))
        # consistency defect: ~1% have a mismatched total
        recorded_total = round(line_total * random.uniform(1.05, 1.20), 2) \
            if random.random() < 0.01 else round(line_total, 2)
        wo.writerow([oid, cust, odate.isoformat(), currency, recorded_total,
                     random.choice(STATUSES)])
        for ln in lines:
            wi.writerow(ln)
        # referential defect: ~0.2% orphan items (bad order_id)
        if random.random() < 0.002:
            item_id += 1
            pid, price = random.choice(products)
            wi.writerow([item_id, 9_999_999, pid, 1, price, price])

print(f"Done. CSVs written to {OUT}")
