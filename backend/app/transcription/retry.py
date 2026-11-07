"""Bounded retry with exponential backoff.

Three properties matter more than the algorithm.

**Only transient failures are retried.** The decision comes from the error's
own `retryable` flag (see `app.transcription.errors`), not from a list of
status codes maintained here. Retrying a 401 cannot succeed and retrying
invalid audio cannot succeed; both just delay the report and spend quota.

**The provider's own guidance wins.** A `RateLimitError` carrying `retry_after`
waits that long, clamped to the configured ceiling. Computing our own backoff
while the provider has told us exactly when to come back is how a client gets
itself throttled harder.

**Streaming is never retried here.** Replaying a stream means replaying the
audio, and the audio has already been consumed from a one-shot iterator - the
caller is a live call, not a buffer. A silent retry would transcribe the tail
of an utterance and present it as the whole thing. `transcribe_stream` is
therefore not wrapped; a failed stream surfaces as `TranscriptionFailed` with
`retryable` set, and the decision to start a new stream belongs to the caller
that still has the audio.

Jitter is on by default and uses a caller-supplied random function, so tests
pin it to a constant and assert exact delays instead of ranges.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.transcription.errors import TranscriptionError

logger = logging.getLogger("bhashabench.transcription.retry")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How many times to retry, and how long to wait between attempts.

    `max_attempts` counts total attempts, not retries: 1 means "try once, do
    not retry". Expressing it this way removes the off-by-one argument about
    whether `max_retries = 0` disables retrying or disables the request.
    """

    max_attempts: int = 3
    initial_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 8.0
    multiplier: float = 2.0
    jitter: bool = True

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must not be negative")
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds must not be below initial_backoff_seconds")
        if self.multiplier < 1:
            raise ValueError("multiplier must be at least 1")

    def backoff_for(
        self,
        attempt: int,
        *,
        retry_after: float | None = None,
        rand: Callable[[], float] = random.random,
    ) -> float:
        """Seconds to wait before `attempt` (1-based: the delay after attempt 1).

        The ceiling is applied to the provider's `retry_after` too. An
        unbounded wait taken on a provider's word turns one throttled request
        into a request that appears to hang.
        """
        if retry_after is not None:
            return min(max(retry_after, 0.0), self.max_backoff_seconds)

        raw = self.initial_backoff_seconds * (self.multiplier ** (attempt - 1))
        delay = min(raw, self.max_backoff_seconds)
        if self.jitter:
            # Full jitter: uniform in [0, delay]. Spreads a thundering herd of
            # concurrent calls far better than an equal-jitter band.
            delay *= rand()
        return delay


async def call_with_retry[T](
    operation: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    provider: str,
    operation_name: str,
    correlation_id: str | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rand: Callable[[], float] = random.random,
) -> tuple[T, int]:
    """Run `operation`, retrying transient failures per `policy`.

    `operation` must be a zero-argument coroutine factory, called afresh on
    each attempt - passing a single awaitable would fail on the second attempt,
    because a coroutine cannot be awaited twice.

    Returns:
        The operation's result and the number of attempts made, so the caller
        can record attempts on the result rather than inferring them.

    Raises:
        TranscriptionError: the last failure, once attempts are exhausted or
            the failure is permanent. The original error is re-raised rather
            than wrapped, so its type, status code and request id survive.
        asyncio.CancelledError: propagated untouched. Cancellation is not a
            provider failure and must never be retried.
    """
    last_error: TranscriptionError | None = None

    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await operation(), attempt
        except asyncio.CancelledError:
            # Must come before TranscriptionError: swallowing cancellation
            # here would leave a cancelled request running to completion.
            raise
        except TranscriptionError as exc:
            last_error = exc

            if not exc.retryable:
                logger.info(
                    "transcription.attempt_failed_permanently",
                    extra={
                        "provider": provider,
                        "operation": operation_name,
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                        "status_code": exc.status_code,
                        "correlation_id": correlation_id,
                    },
                )
                raise

            if attempt == policy.max_attempts:
                logger.warning(
                    "transcription.retries_exhausted",
                    extra={
                        "provider": provider,
                        "operation": operation_name,
                        "attempts": attempt,
                        "error_type": type(exc).__name__,
                        "correlation_id": correlation_id,
                    },
                )
                raise

            retry_after = getattr(exc, "retry_after", None)
            delay = policy.backoff_for(attempt, retry_after=retry_after, rand=rand)
            logger.info(
                "transcription.retrying",
                extra={
                    "provider": provider,
                    "operation": operation_name,
                    "attempt": attempt,
                    "next_attempt_in_seconds": round(delay, 3),
                    "error_type": type(exc).__name__,
                    "correlation_id": correlation_id,
                },
            )
            await sleep(delay)

    # Unreachable: the loop either returns or raises. Kept so the function has
    # no implicit `None` return path if the loop bounds are ever edited.
    raise last_error if last_error else TranscriptionError("retry loop exited without a result")


__all__ = ["RetryPolicy", "call_with_retry"]
