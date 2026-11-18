"""A small load test: concurrent requests against a running BhashaBench API.

    python scripts/load_test.py --base http://127.0.0.1:8000 --requests 2000 --concurrency 50

Reports throughput and latency percentiles per path, and every non-2xx
status it saw - a load test that hides its errors measures nothing. Paths
are public (liveness and the language catalogue) unless `--token` is given,
in which case the authenticated run listing is added. Run the server with
`RATE_LIMIT_REQUESTS_PER_MINUTE=0`, or the limiter (correctly) answers 429.

No dependency beyond the backend's own httpx2. The numbers describe the
machine it ran on; record them with that machine, never as a capacity claim.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from collections import Counter

import httpx2


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[max(int(round(p / 100 * len(ordered))) - 1, 0)]


async def run(base: str, path: str, total: int, concurrency: int, headers: dict[str, str]) -> None:
    latencies: list[float] = []
    statuses: Counter[int] = Counter()
    errors: Counter[str] = Counter()
    queue = asyncio.Queue[int]()
    for i in range(total):
        queue.put_nowait(i)
    async with httpx2.AsyncClient(base_url=base, timeout=30, headers=headers) as client:

        async def worker() -> None:
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                start = time.perf_counter()
                try:
                    response = await client.get(path)
                    statuses[response.status_code] += 1
                except httpx2.HTTPError as exc:
                    errors[type(exc).__name__] += 1
                    continue
                latencies.append((time.perf_counter() - start) * 1000)

        started = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(concurrency)))
        elapsed = time.perf_counter() - started
    ok = sum(n for s, n in statuses.items() if 200 <= s < 300)
    print(f"{path}: {total} requests, concurrency {concurrency}, {elapsed:.2f} s, "
          f"{total / elapsed:.0f} req/s")
    if latencies:
        print(f"  latency ms  p50 {percentile(latencies, 50):.1f}  p95 {percentile(latencies, 95):.1f}  "
              f"p99 {percentile(latencies, 99):.1f}  mean {statistics.fmean(latencies):.1f}")
    print(f"  2xx {ok}  other statuses {dict(s for s in statuses.items() if not 200 <= s[0] < 300)}"
          f"  transport errors {dict(errors)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--token", default="", help="bearer token for the authenticated path")
    args = parser.parse_args()
    paths = ["/health", "/api/v1/languages"]
    headers = {}
    if args.token:
        paths.append("/api/v1/test-runs?limit=20")
        headers["Authorization"] = f"Bearer {args.token}"
    for path in paths:
        asyncio.run(run(args.base, path, args.requests, args.concurrency, headers))


if __name__ == "__main__":
    main()
