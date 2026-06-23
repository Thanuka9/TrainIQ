#!/usr/bin/env python3
"""Apply PostgreSQL migrations and ensure MongoDB indexes — delegates to db_platform."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    from app import app

    print("=== TrainIQ DB Platform bootstrap ===")
    with app.app_context():
        from utils.db_platform import bootstrap_database, ensure_database_healthy

        result = bootstrap_database(include_mongo=True)
        print("Bootstrap:", result.get('status'))
        for step in result.get('steps', []):
            mark = "OK" if step.get('ok') else "FAIL"
            print(f"  [{mark}] {step.get('step')}: {step.get('message')}")

        print("=== Health scan + safe indexes ===")
        health = ensure_database_healthy(apply_safe=True)
        print(health)

    print("=== Done — no manual SQL required ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
