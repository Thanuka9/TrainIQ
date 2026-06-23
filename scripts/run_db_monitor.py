#!/usr/bin/env python
"""Run DB health scan — uses platform_ops_orchestrator."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    parser = argparse.ArgumentParser(description='Run TrainIQ DB health scan via db_platform.')
    parser.add_argument(
        '--apply-safe',
        action='store_true',
        help='Apply safe-tier optimizations after scan.',
    )
    parser.add_argument(
        '--apply-all',
        action='store_true',
        help='Apply safe + manual optimizations after scan.',
    )
    args = parser.parse_args()

    from app import app

    with app.app_context():
        if args.apply_all:
            from utils.db_optimizer_agent import apply_all_pending_recommendations
            from utils.platform_ops_orchestrator import run_health_cycle

            cycle = run_health_cycle(source='cli', apply_safe=False, blocking_lock=True)
            monitor = cycle.get('monitor') or {}
            applied = apply_all_pending_recommendations(monitor.get('snapshot_id'))
            print({'cycle': cycle, 'applied': applied})
        elif args.apply_safe:
            from utils.platform_ops_orchestrator import run_health_cycle

            print(run_health_cycle(source='cli', apply_safe=True, blocking_lock=True))
        else:
            from utils.platform_ops_orchestrator import run_health_cycle

            print(run_health_cycle(source='cli', apply_safe=False, blocking_lock=True))


if __name__ == '__main__':
    main()
