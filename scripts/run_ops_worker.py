#!/usr/bin/env python
"""Dedicated ops worker — runs APScheduler jobs + optional event bus consumer.

Usage:
  set RUN_SCHEDULER=true
  set OPS_WORKER_MODE=true
  set EVENT_BUS_CONSUMER=true
  python scripts/run_ops_worker.py
"""
from __future__ import annotations

import os
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('RUN_SCHEDULER', 'true')
os.environ.setdefault('OPS_WORKER_MODE', 'true')
os.environ.setdefault('EVENT_BUS_CONSUMER', 'true')


def main():
    from app import app, scheduler
    from utils.service_mode import event_bus_consumer_enabled

    if not scheduler.running:
        print('Scheduler did not start — check RUN_SCHEDULER and app logs.', file=sys.stderr)
        sys.exit(1)

    print('TrainIQ ops worker running. Scheduled jobs:')
    for job in scheduler.get_jobs():
        print(f'  - {job.id}: next={job.next_run_time}')

    consumer = event_bus_consumer_enabled()
    consumer_name = f'worker-{uuid.uuid4().hex[:8]}'
    if consumer:
        print(f'Event bus consumer enabled ({consumer_name})')

    with app.app_context():
        while True:
            if consumer:
                try:
                    from utils.event_bus import consume_ops_events

                    n = consume_ops_events(consumer_name=consumer_name, count=10, block_ms=1000)
                    if n:
                        print(f'Processed {n} event bus message(s)')
                except Exception as exc:
                    print(f'Event bus error: {exc}', file=sys.stderr)
            time.sleep(5 if consumer else 60)


if __name__ == '__main__':
    main()
