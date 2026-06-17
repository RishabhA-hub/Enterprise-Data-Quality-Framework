"""
generate_all.py
---------------
Orchestrator: runs the three generators in the correct order so that the
sales generator can reference real customer/employee IDs.

Usage (from project root):

    python -m dq_framework.python.generate_all
"""

from dq_framework.python.generators import (
    generate_customers,
    generate_employees,
    generate_sales,
)


def main() -> None:
    print("=" * 60)
    print("DQ Framework -- Step 2: Synthetic Data Generation")
    print("=" * 60)
    generate_customers.main()
    generate_employees.main()
    generate_sales.main()  # depends on the two above
    print("-" * 60)
    print("Done. Clean files     -> data/raw/")
    print("     Corrupted files -> data/corrupted/  (load into staging)")


if __name__ == "__main__":
    main()
