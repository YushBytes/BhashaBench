"""How many pipeline runs may execute at once, and what happens at the limit.

`PIPELINE_MAX_CONCURRENT_RUNS` existed from Phase 7 and was read by nothing:
the number was documented, recorded in the run metadata, and enforced by
nobody. This module is the consumer it was missing.

**Why a counting guard rather than `asyncio.Semaphore`.** Two reasons, and the
first is the one that matters.

A semaphore that *waits* holds pending waiters, and a waiter belongs to the
event loop that created it. The run engine is driven by `asyncio.run` in tests
and by the server's loop in production, so a process-wide `asyncio.Semaphore`
with waiters would eventually be awaited from a loop other than the one a
waiter was parked on - which raises, intermittently, under exactly the
concurrency it exists to control. This limiter never waits, so it never holds a
waiter, so it has no loop affinity at all.

Second, waiting is the wrong behaviour here anyway. §5 of the brief is explicit:
do not silently queue unlimited work. A request that queues behind an unbounded
line of other requests has no bound on its own latency, and the client cannot
tell a slow run from a stuck one. Refusing immediately is the predictable
answer - the run keeps its state, nothing is lost, and the client retries.

So: a counter, guarded for mutation, that either admits a run or refuses it.
That is a non-blocking counting semaphore; it is simply not
`asyncio.Semaphore`.

**Thread safety.** The counter is mutated under a `threading.Lock` held for the
check-and-increment only and never across an `await`. On the event loop the
lock is redundant - there is no await between the test and the increment, so
the sequence is already atomic - but FastAPI runs synchronous handlers in a
worker thread, and a future caller from one of those would otherwise be racing.
The lock costs nothing uncontended and removes the question.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache

from app.core.config import Settings
from app.pipeline.errors import RunCapacityExhaustedError

logger = logging.getLogger("bhashabench.pipeline.concurrency")


class RunSlots:
    """A bounded, non-blocking count of concurrently executing runs.

    One instance per process per configured limit. `acquire` admits a run or
    raises `RunCapacityExhaustedError`; it never blocks and never queues.
    """

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError(f"the concurrent-run limit must be at least 1, got {limit}")
        self._limit = limit
        self._in_use = 0
        self._lock = threading.Lock()
        self._peak = 0

    @property
    def limit(self) -> int:
        """The configured maximum."""
        return self._limit

    @property
    def in_use(self) -> int:
        """How many runs are executing right now."""
        with self._lock:
            return self._in_use

    @property
    def available(self) -> int:
        """How many more runs could start right now."""
        with self._lock:
            return self._limit - self._in_use

    @property
    def peak_in_use(self) -> int:
        """The highest concurrent count this instance has seen.

        Kept so a test can assert the limit was never exceeded *during* a run
        rather than only after it - an assertion on `in_use` at the end proves
        nothing, because by then everything has been released.
        """
        with self._lock:
            return self._peak

    def _take(self) -> None:
        """Claim a slot, or refuse.

        Raises:
            RunCapacityExhaustedError: every slot is in use.
        """
        with self._lock:
            if self._in_use >= self._limit:
                raise RunCapacityExhaustedError(
                    f"all {self._limit} concurrent run slots are in use; this run "
                    "was not started and keeps its current state, so retry it "
                    "when a slot frees up. Raise PIPELINE_MAX_CONCURRENT_RUNS "
                    "only if the machine can afford the extra provider calls and "
                    "memory.",
                    limit=self._limit,
                    in_use=self._in_use,
                )
            self._in_use += 1
            self._peak = max(self._peak, self._in_use)

    def _give_back(self) -> None:
        """Release a slot.

        Clamped at zero rather than allowed to go negative: a double release
        would otherwise hand out phantom capacity for the life of the process,
        which is a worse failure than the bug that caused it.
        """
        with self._lock:
            if self._in_use == 0:  # pragma: no cover - guards a caller bug
                logger.error("pipeline.slot_released_without_being_held")
                return
            self._in_use -= 1

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        """Hold a slot for the duration of the block.

        The `finally` is what satisfies the release requirement on all four
        exits - normal completion, an exception, `asyncio.CancelledError` and a
        timeout are all unwinds through this frame, and none of them can skip
        it.

        Raises:
            RunCapacityExhaustedError: no slot was free.
        """
        self._take()
        try:
            yield
        finally:
            self._give_back()

    @contextmanager
    def hold_sync(self) -> Iterator[None]:
        """Synchronous equivalent, for a caller not on the event loop."""
        self._take()
        try:
            yield
        finally:
            self._give_back()

    def reset(self) -> None:
        """Drop the count and the peak.

        For tests only. A shared instance that kept a leaked slot would make
        every later test in the process fail for the first one's reason.
        """
        with self._lock:
            self._in_use = 0
            self._peak = 0


@lru_cache
def slots_for_limit(limit: int) -> RunSlots:
    """The process-wide `RunSlots` for one limit.

    Cached on the limit rather than hung off the application object, mirroring
    `get_settings`: the limiter has to be shared across every request for it to
    limit anything, and a per-request instance would enforce nothing - which is
    precisely how the setting came to be unused. Tests vary the limit to get a
    distinct instance, or call `slots_for_limit.cache_clear()`.
    """
    return RunSlots(limit)


def get_run_slots(settings: Settings) -> RunSlots:
    """The limiter for the configured maximum."""
    return slots_for_limit(settings.pipeline_max_concurrent_runs)


__all__ = ["RunSlots", "get_run_slots", "slots_for_limit"]
