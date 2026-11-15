"""The live-spending controls: an authorisation gate and a durable budget.

Two independent things stand between this codebase and a billable request,
and both must agree before one is sent.

**The gate.** `LIVE_CALLS_AUTHORISED` is a constant in this file, and it is
`False`. The project owner has approved a budget for live testing and has
*not* approved live testing itself, so no configuration value, credential or
free-credit balance can enable a live language-model call: the environment
flag (`CALLER_LLM_LIVE_CALLS_ENABLED`) is necessary and not sufficient.
Changing the constant is a reviewed commit that records the owner's approval,
which is the point - an approval should not be something a `.env` edit can
impersonate.

**The budget.** `LiveBudget` is a ledger in a file, so the ceiling holds
across requests, workers and restarts rather than per process. A request
*reserves* its worst-case cost before it is sent and is refused if that would
not fit; afterwards the reservation is lowered to the reported cost, or left
at the worst case when the provider reported no usage or the request failed
after leaving the process. Nothing here ever lowers a charge to zero.

The ceiling is the lower of the configured budget and `HARD_LIVE_BUDGET_INR`.
The second is the owner's stated maximum; configuration can tighten it and
cannot raise it.

Known limit, stated rather than hidden: the ledger is a local file. Deleting
it resets the count, and two machines keep two ledgers. It bounds what this
checkout spends; the provider's own dashboard is the authority on the bill.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from app.caller.llm.errors import BudgetExceededError, LiveCallsDisabledError

LIVE_CALLS_AUTHORISED: bool = False
"""Whether the owner has approved live language-model calls. They have not.

Do not change this without the owner's explicit instruction to begin live
testing. A budget ceiling is not that instruction.
"""

HARD_LIVE_BUDGET_INR = Decimal(100)
"""The most Phase 6 live testing may ever cost, in rupees. Not configurable."""

LEDGER_CURRENCY = "INR"

_LOCK_ATTEMPTS = 40
_LOCK_WAIT_SECONDS = 0.025
_FILE_VERSION = 1


def require_live_calls(*, enabled_in_configuration: bool, provider: str) -> None:
    """Refuse unless live calls are both authorised in code and switched on.

    Raises:
        LiveCallsDisabledError: always, today. Its message names which of the
            two conditions failed, so an operator is not sent to edit a
            setting that could not have helped.
    """
    if not LIVE_CALLS_AUTHORISED:
        raise LiveCallsDisabledError(
            "live language-model calls are not authorised: the project owner has not "
            "approved live testing, and no setting or credential can enable it",
            provider=provider,
        )
    if not enabled_in_configuration:
        raise LiveCallsDisabledError(
            "live language-model calls are switched off; CALLER_LLM_LIVE_CALLS_ENABLED is false",
            provider=provider,
        )


@dataclass(frozen=True, slots=True)
class Reservation:
    """An amount committed to the ledger for one request that is about to be sent."""

    amount: Decimal


class LiveBudget:
    """A file-backed ledger of what live calls have been committed to cost."""

    def __init__(self, path: Path, *, ceiling: Decimal, provider: str = "llm") -> None:
        if ceiling < 0:
            raise ValueError("a budget ceiling must not be negative")
        self._path = path
        self._lock_path = path.with_name(path.name + ".lock")
        self._ceiling = min(ceiling, HARD_LIVE_BUDGET_INR)
        self._provider = provider
        self._thread_lock = threading.Lock()

    @property
    def ceiling(self) -> Decimal:
        """The effective ceiling: never above `HARD_LIVE_BUDGET_INR`."""
        return self._ceiling

    @property
    def path(self) -> Path:
        return self._path

    # -- Public operations --------------------------------------------------

    def committed(self) -> Decimal:
        """Everything reserved or charged so far."""
        with self._exclusive():
            return self._read()

    def remaining(self) -> Decimal:
        return max(self._ceiling - self.committed(), Decimal(0))

    def reserve(self, amount: Decimal, *, currency: str) -> Reservation:
        """Commit `amount` before a request is sent, or refuse.

        Raises:
            BudgetExceededError: the amount does not fit what is left, the
                currency is not the ledger's, or the ledger cannot be read.
        """
        if currency != LEDGER_CURRENCY:
            raise BudgetExceededError(
                f"the live budget is kept in {LEDGER_CURRENCY}; a cost in {currency} "
                "cannot be compared with it, so the request is refused",
                provider=self._provider,
            )
        if amount <= 0:
            # A request that claims to cost nothing has an unknown cost.
            raise BudgetExceededError(
                "a live request must have a positive worst-case cost; an unknown "
                "cost is not treated as zero",
                provider=self._provider,
            )
        with self._exclusive():
            committed = self._read()
            if committed + amount > self._ceiling:
                raise BudgetExceededError(
                    f"this request could cost up to {amount} {LEDGER_CURRENCY}, but "
                    f"{committed} of the {self._ceiling} {LEDGER_CURRENCY} live budget "
                    "is already committed",
                    provider=self._provider,
                )
            self._write(committed + amount)
        return Reservation(amount=amount)

    def settle(self, reservation: Reservation, actual: Decimal | None) -> None:
        """Replace a reservation with what the request is known to have cost.

        `actual=None` means the cost is not known - no usage was reported, or
        the request failed after it was sent - and the worst case stands. An
        actual above the reservation is recorded in full: the ledger reports
        what was spent even when that is more than was expected.
        """
        if actual is None or actual == reservation.amount:
            return
        if actual < 0:
            raise ValueError("an actual cost must not be negative")
        with self._exclusive():
            committed = self._read()
            self._write(max(committed - reservation.amount + actual, Decimal(0)))

    # -- File handling ------------------------------------------------------

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Hold the ledger across threads and across processes.

        The lock file is created with `O_EXCL`, which is atomic on every
        platform this runs on. A lock that cannot be taken refuses the request
        rather than proceeding unlocked: a stale lock stops spending, which is
        the safe way for this to fail.
        """
        with self._thread_lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle: int | None = None
            for _ in range(_LOCK_ATTEMPTS):
                try:
                    handle = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    break
                except FileExistsError:
                    time.sleep(_LOCK_WAIT_SECONDS)
                except OSError as exc:
                    raise BudgetExceededError(
                        f"the live budget ledger could not be locked ({type(exc).__name__}); "
                        "refusing to spend without it",
                        provider=self._provider,
                    ) from exc
            if handle is None:
                raise BudgetExceededError(
                    f"the live budget ledger is locked by another process ({self._lock_path}); "
                    "refusing to spend without it. Remove the lock file if no process holds it.",
                    provider=self._provider,
                )
            try:
                yield
            finally:
                os.close(handle)
                with suppress(OSError):
                    os.unlink(self._lock_path)

    def _read(self) -> Decimal:
        """The committed total. A missing file is zero; an unreadable one is not."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return Decimal(0)
        except OSError as exc:
            raise self._unreadable(type(exc).__name__) from exc
        try:
            document = json.loads(raw)
            if document["currency"] != LEDGER_CURRENCY:
                raise ValueError("unexpected currency")
            committed = Decimal(str(document["committed"]))
        except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
            raise self._unreadable("it is not a valid ledger") from exc
        if not committed.is_finite() or committed < 0:
            raise self._unreadable("it holds an impossible total")
        return committed

    def _unreadable(self, why: str) -> BudgetExceededError:
        return BudgetExceededError(
            f"the live budget ledger at {self._path} could not be read ({why}); what has "
            "been spent is unknown, so the request is refused rather than assumed affordable",
            provider=self._provider,
        )

    def _write(self, committed: Decimal) -> None:
        document = {
            "version": _FILE_VERSION,
            "currency": LEDGER_CURRENCY,
            "committed": str(committed),
            "ceiling": str(self._ceiling),
        }
        temporary = self._path.with_name(self._path.name + ".tmp")
        temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self._path)


@lru_cache(maxsize=8)
def shared_budget(path: Path, ceiling: Decimal, provider: str) -> LiveBudget:
    """The one `LiveBudget` for a ledger file.

    Cached for the reason the pipeline's concurrency limiter is: a caller
    provider is built per request, and a per-request ledger object would hold
    a per-request thread lock that serialises nothing.
    """
    return LiveBudget(path, ceiling=ceiling, provider=provider)


__all__ = [
    "HARD_LIVE_BUDGET_INR",
    "LEDGER_CURRENCY",
    "LIVE_CALLS_AUTHORISED",
    "LiveBudget",
    "Reservation",
    "require_live_calls",
    "shared_budget",
]
