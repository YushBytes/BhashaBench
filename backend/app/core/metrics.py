"""Operational metrics (Phase 15), in the Prometheus text format.

Counted in process memory, so they reset on restart and each worker counts
its own (the same per-process caveat as the rate limiter). Exposed at
`GET /metrics` only when `METRICS_TOKEN` is set, and only to a request
bearing it - a metrics page says how busy the service is and which errors
it returns, which is not for the public. Unset, the route answers 404 as if
it did not exist.

What is measured, and nothing else:

- `bhashabench_http_requests_total{method,status_class}` - responses sent;
- `bhashabench_http_request_seconds_sum` / `_count` - total time handling them;
- `bhashabench_rate_limited_total` - requests answered 429;
- `bhashabench_test_runs{status}` - runs by stored status, read from the
  database at scrape time (a gauge, not a counter).
"""

from __future__ import annotations

import threading
from collections import Counter


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: Counter[tuple[str, str]] = Counter()
        self.seconds_sum = 0.0
        self.seconds_count = 0
        self.rate_limited = 0

    def observe(self, method: str, status: int, seconds: float) -> None:
        with self._lock:
            self.requests[(method, f"{status // 100}xx")] += 1
            self.seconds_sum += seconds
            self.seconds_count += 1
            if status == 429:
                self.rate_limited += 1

    def render(self, runs_by_status: dict[str, int]) -> str:
        with self._lock:
            lines = [
                "# HELP bhashabench_http_requests_total HTTP responses sent.",
                "# TYPE bhashabench_http_requests_total counter",
                *(
                    f'bhashabench_http_requests_total{{method="{m}",status_class="{c}"}} {n}'
                    for (m, c), n in sorted(self.requests.items())
                ),
                "# HELP bhashabench_http_request_seconds Time spent handling requests.",
                "# TYPE bhashabench_http_request_seconds summary",
                f"bhashabench_http_request_seconds_sum {self.seconds_sum:.6f}",
                f"bhashabench_http_request_seconds_count {self.seconds_count}",
                "# HELP bhashabench_rate_limited_total Requests answered 429.",
                "# TYPE bhashabench_rate_limited_total counter",
                f"bhashabench_rate_limited_total {self.rate_limited}",
            ]
        lines += [
            "# HELP bhashabench_test_runs Test runs by stored status.",
            "# TYPE bhashabench_test_runs gauge",
            *(
                f'bhashabench_test_runs{{status="{s}"}} {n}'
                for s, n in sorted(runs_by_status.items())
            ),
        ]
        return "\n".join(lines) + "\n"


__all__ = ["Metrics"]
