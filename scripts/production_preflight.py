#!/usr/bin/env python
"""Production preflight — run before deploy or first gunicorn start.

Usage:
  set FLASK_ENV=production
  set DATABASE_URL=...
  python scripts/production_preflight.py

Exit 0 when all required checks pass.
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(override=True)


def main() -> int:
    parser = argparse.ArgumentParser(description='TrainIQ production preflight')
    parser.add_argument('--skip-connectivity', action='store_true')
    parser.add_argument('--skip-migrations', action='store_true')
    parser.add_argument('--generate-secret', action='store_true', help='Print a SECRET_KEY and exit')
    args = parser.parse_args()

    if args.generate_secret:
        from utils.production_preflight import generate_secret_key

        print(generate_secret_key())
        return 0

    from utils.production_preflight import is_production_env, run_preflight

    mode = 'production' if is_production_env() else 'development'
    print(f'TrainIQ preflight ({mode})')
    print('-' * 40)

    ok, results = run_preflight(
        skip_connectivity=args.skip_connectivity,
        skip_migrations=args.skip_migrations,
    )

    for r in results:
        flag = 'OK  ' if r['ok'] else 'FAIL'
        req = 'required' if r.get('required', True) else 'optional'
        print(f'  [{flag}] {r["name"]} ({req}): {r["detail"]}')

    print('-' * 40)
    if ok:
        print('Preflight PASSED — safe to start web workers.')
        return 0

    print('Preflight FAILED — fix required items before production traffic.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
