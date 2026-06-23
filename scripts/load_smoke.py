#!/usr/bin/env python
"""Lightweight load smoke test against a running TrainIQ instance."""
from __future__ import annotations

import argparse
import concurrent.futures
import sys
import time

import requests


def _hit(url: str, timeout: float) -> tuple[int, float]:
    start = time.perf_counter()
    try:
        r = requests.get(url, timeout=timeout, allow_redirects=False)
        return r.status_code, time.perf_counter() - start
    except Exception:
        return 0, time.perf_counter() - start


def main():
    parser = argparse.ArgumentParser(description='TrainIQ load smoke test')
    parser.add_argument('--url', default='http://127.0.0.1:5000', help='Base URL')
    parser.add_argument('--path', default='/auth/login', help='Path to request')
    parser.add_argument('--requests', type=int, default=50)
    parser.add_argument('--workers', type=int, default=10)
    parser.add_argument('--timeout', type=float, default=10.0)
    args = parser.parse_args()

    target = args.url.rstrip('/') + args.path
    print(f'Load smoke: {args.requests} GET {target} ({args.workers} workers)')

    results: list[tuple[int, float]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(_hit, target, args.timeout) for _ in range(args.requests)]
        for fut in concurrent.futures.as_completed(futs):
            results.append(fut.result())

    codes = [c for c, _ in results if c]
    latencies = [t for _, t in results]
    ok = sum(1 for c in codes if 200 <= c < 400)
    print(f'OK: {ok}/{args.requests}  errors: {args.requests - len(codes)}')
    if latencies:
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95) - 1]
        print(f'Latency p50={p50:.3f}s p95={p95:.3f}s max={max(latencies):.3f}s')

    sys.exit(0 if ok >= args.requests * 0.9 else 1)


if __name__ == '__main__':
    main()
