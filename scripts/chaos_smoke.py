#!/usr/bin/env python
"""Chaos smoke — verify event bus degrades gracefully when Redis is unavailable."""
from __future__ import annotations

import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description='TrainIQ chaos smoke (Redis event bus)')
    parser.add_argument('--redis-uri', default=os.getenv('REDIS_URI', 'redis://127.0.0.1:9/0'))
    args = parser.parse_args()

    os.environ['REDIS_URI'] = args.redis_uri
    os.environ['EVENT_BUS_ENABLED'] = 'true'

    from utils.event_bus import consume_ops_events, event_bus_enabled, publish_ops_event

    if event_bus_enabled():
        print('Unexpected: event bus connected to bad Redis URI')
        sys.exit(1)

    assert publish_ops_event('chaos.test', {'x': 1}) is None
    assert consume_ops_events(consumer_name='chaos', count=1, block_ms=100) == 0
    print('Event bus gracefully disabled when Redis unavailable — OK')
    sys.exit(0)


if __name__ == '__main__':
    main()
