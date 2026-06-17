"""Thin CLI wrapper: `python -m rules_engine.run_rules --table stg_customer`"""
from .engine import main

if __name__ == "__main__":
    main()
