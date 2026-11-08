"""The concurrent-run limiter.

`PIPELINE_MAX_CONCURRENT_RUNS` was a documented number with no consumer until
Phase 7.1. These tests are what make the enforcement real rather than claimed.

**Determinism.** Nothing here sleeps for a fixed period and hopes the
interleaving comes out right. Every test that needs two runs genuinely
overlapping uses an `asyncio.Event` as a gate: run A enters the critical
section and blocks on the event, the test then observes the limiter's state and
starts run B, and only afterwards releases A. The ordering is therefore forced
rather than raced, so these tests cannot flake.

`peak_in_use` carries most of the weight. Asserting `in_use == 0` at the end
proves nothing - by then everything has been released whether the limit held or
not - so the assertions are on the highest concurrency the limiter ever saw.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.pipeline.concurrency import RunSlots, get_run_slots, slots_for_limit
from app.pipeline.errors import PipelineError, RunCapacityExhaustedError
from app.pipeline.modes import ExecutionMode

RUN_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
RUN_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
RUN_C = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


# ---------------------------------------------------------------------------
# The limiter in isolation
# ---------------------------------------------------------------------------


class TestRunSlots:
    def test_a_fresh_limiter_is_entirely_free(self) -> None:
        slots = RunSlots(3)
        assert slots.limit == 3
        assert slots.in_use == 0
        assert slots.available == 3
        assert slots.peak_in_use == 0

    def test_a_zero_limit_is_refused_at_construction(self) -> None:
        """A limit of zero would admit nothing ever, which is a configuration
        mistake rather than a policy. The settings field already enforces
        `ge=1`; this is the second line of defence for a direct caller."""
        with pytest.raises(ValueError, match="at least 1"):
            RunSlots(0)

    def test_holding_a_slot_consumes_capacity(self) -> None:
        slots = RunSlots(2)

        async def exercise() -> None:
            async with slots.hold():
                assert slots.in_use == 1
                assert slots.available == 1
            assert slots.in_use == 0

        asyncio.run(exercise())

    def test_capacity_is_released_on_a_normal_exit(self) -> None:
        slots = RunSlots(1)

        async def exercise() -> None:
            async with slots.hold():
                pass
            async with slots.hold():
                pass

        asyncio.run(exercise())
        assert slots.in_use == 0
        assert slots.peak_in_use == 1

    def test_capacity_is_released_when_the_body_raises(self) -> None:
        """Otherwise one failing run would permanently cost the process a
        slot, and enough failures would wedge it completely."""
        slots = RunSlots(1)

        async def exercise() -> None:
            with pytest.raises(RuntimeError):
                async with slots.hold():
                    raise RuntimeError("the run blew up")

        asyncio.run(exercise())
        assert slots.in_use == 0
        assert slots.available == 1

    def test_capacity_is_released_on_cancellation(self) -> None:
        slots = RunSlots(1)
        entered = asyncio.Event()

        async def holder() -> None:
            async with slots.hold():
                entered.set()
                await asyncio.sleep(3600)

        async def exercise() -> None:
            task = asyncio.create_task(holder())
            await entered.wait()
            assert slots.in_use == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(exercise())
        assert slots.in_use == 0
        assert slots.available == 1

    def test_capacity_is_released_on_a_timeout(self) -> None:
        slots = RunSlots(1)

        async def exercise() -> None:
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.01), slots.hold():
                    await asyncio.sleep(3600)

        asyncio.run(exercise())
        assert slots.in_use == 0
        assert slots.available == 1

    def test_the_limit_is_refused_rather_than_queued(self) -> None:
        """The whole policy in one assertion: a refusal is immediate, not a
        wait. A queued request has no bound on its own latency."""
        slots = RunSlots(1)

        async def exercise() -> None:
            # Nested, not combined: `pytest.raises` is a synchronous context
            # manager, so folding it into the `async with` raises TypeError.
            async with slots.hold():
                with pytest.raises(RunCapacityExhaustedError):
                    async with slots.hold():
                        pytest.fail("a second slot was handed out over the limit")

        asyncio.run(exercise())

    def test_the_refusal_names_the_limit_it_hit(self) -> None:
        slots = RunSlots(2)

        async def exercise() -> None:
            async with slots.hold(), slots.hold():
                with pytest.raises(RunCapacityExhaustedError) as caught:
                    async with slots.hold():
                        pass
                assert caught.value.limit == 2
                assert caught.value.in_use == 2
                assert "PIPELINE_MAX_CONCURRENT_RUNS" in str(caught.value)

        asyncio.run(exercise())

    def test_a_refused_acquisition_consumes_nothing(self) -> None:
        """A failed `_take` must not leave the counter incremented, or the
        limiter leaks capacity every time it refuses."""
        slots = RunSlots(1)

        async def exercise() -> None:
            async with slots.hold():
                for _ in range(5):
                    with pytest.raises(RunCapacityExhaustedError):
                        async with slots.hold():
                            pass
                assert slots.in_use == 1

        asyncio.run(exercise())
        assert slots.in_use == 0

    def test_capacity_frees_up_for_the_next_run(self) -> None:
        slots = RunSlots(1)

        async def exercise() -> None:
            async with slots.hold():
                with pytest.raises(RunCapacityExhaustedError):
                    async with slots.hold():
                        pass
            # The first has released; the next one is admitted.
            async with slots.hold():
                assert slots.in_use == 1

        asyncio.run(exercise())
        assert slots.peak_in_use == 1

    def test_exactly_the_limit_is_admitted_and_no_more(self) -> None:
        slots = RunSlots(3)

        async def exercise() -> None:
            async with slots.hold(), slots.hold(), slots.hold():
                assert slots.in_use == 3
                assert slots.available == 0
                with pytest.raises(RunCapacityExhaustedError):
                    async with slots.hold():
                        pass

        asyncio.run(exercise())
        assert slots.peak_in_use == 3

    def test_the_synchronous_holder_shares_the_same_count(self) -> None:
        """A caller off the event loop must not get its own private budget."""
        slots = RunSlots(1)
        with slots.hold_sync():
            assert slots.in_use == 1
            with pytest.raises(RunCapacityExhaustedError), slots.hold_sync():
                pass
        assert slots.in_use == 0

    def test_the_synchronous_holder_releases_on_an_exception(self) -> None:
        slots = RunSlots(1)
        with pytest.raises(RuntimeError), slots.hold_sync():
            raise RuntimeError("boom")
        assert slots.available == 1

    def test_reset_clears_the_count_and_the_peak(self) -> None:
        slots = RunSlots(2)

        async def exercise() -> None:
            async with slots.hold():
                pass

        asyncio.run(exercise())
        assert slots.peak_in_use == 1
        slots.reset()
        assert slots.in_use == 0
        assert slots.peak_in_use == 0

    def test_the_limiter_survives_being_used_from_successive_event_loops(
        self,
    ) -> None:
        """The reason this is a counter and not an `asyncio.Semaphore`.

        A semaphore that waits parks its waiters on one loop; awaiting it from
        another raises. This limiter never waits, so it has no loop affinity -
        and three separate `asyncio.run` calls, which is what the rest of this
        suite does, must not disturb it.
        """
        slots = RunSlots(1)
        for _ in range(3):

            async def exercise() -> None:
                async with slots.hold():
                    assert slots.in_use == 1

            asyncio.run(exercise())
        assert slots.in_use == 0
        assert slots.peak_in_use == 1


class TestTrueOverlap:
    """Two coroutines genuinely in flight at once, with forced ordering."""

    def test_the_limit_is_never_exceeded_under_overlap(self) -> None:
        slots = RunSlots(2)
        observed: list[int] = []
        gate = asyncio.Event()

        async def worker(index: int) -> str:
            try:
                async with slots.hold():
                    observed.append(slots.in_use)
                    await gate.wait()
                    return f"ran-{index}"
            except RunCapacityExhaustedError:
                return f"refused-{index}"

        async def exercise() -> list[str]:
            tasks = [asyncio.create_task(worker(n)) for n in range(5)]
            # Let every task reach either the critical section or the refusal.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            gate.set()
            return await asyncio.gather(*tasks)

        results = asyncio.run(exercise())
        assert slots.peak_in_use == 2
        assert max(observed) == 2
        assert sum(1 for r in results if r.startswith("ran-")) == 2
        assert sum(1 for r in results if r.startswith("refused-")) == 3

    def test_a_released_slot_admits_a_later_arrival(self) -> None:
        """Capacity becoming available is handled by admitting the next
        arrival, not by having kept it waiting."""
        slots = RunSlots(1)
        first_in = asyncio.Event()
        release_first = asyncio.Event()

        async def first() -> None:
            async with slots.hold():
                first_in.set()
                await release_first.wait()

        async def exercise() -> None:
            task = asyncio.create_task(first())
            await first_in.wait()

            # While the first holds the only slot, a second is refused.
            with pytest.raises(RunCapacityExhaustedError):
                async with slots.hold():
                    pass

            release_first.set()
            await task

            # Now the slot is free, and the same request succeeds.
            async with slots.hold():
                assert slots.in_use == 1

        asyncio.run(exercise())
        assert slots.peak_in_use == 1

    def test_a_crashing_run_frees_its_slot_for_an_overlapping_one(self) -> None:
        slots = RunSlots(1)
        crashed = asyncio.Event()

        async def crasher() -> None:
            async with slots.hold():
                crashed.set()
                raise RuntimeError("provider exploded")

        async def exercise() -> None:
            task = asyncio.create_task(crasher())
            with pytest.raises(RuntimeError):
                await task
            assert crashed.is_set()
            async with slots.hold():
                assert slots.in_use == 1

        asyncio.run(exercise())

    def test_a_cancelled_run_frees_its_slot_for_an_overlapping_one(self) -> None:
        slots = RunSlots(1)
        entered = asyncio.Event()

        async def holder() -> None:
            async with slots.hold():
                entered.set()
                await asyncio.sleep(3600)

        async def exercise() -> None:
            task = asyncio.create_task(holder())
            await entered.wait()
            with pytest.raises(RunCapacityExhaustedError):
                async with slots.hold():
                    pass
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            async with slots.hold():
                assert slots.in_use == 1

        asyncio.run(exercise())

    def test_a_timed_out_run_frees_its_slot_for_an_overlapping_one(self) -> None:
        slots = RunSlots(1)
        entered = asyncio.Event()

        async def slow() -> None:
            async with asyncio.timeout(0.02), slots.hold():
                entered.set()
                await asyncio.sleep(3600)

        async def exercise() -> None:
            task = asyncio.create_task(slow())
            await entered.wait()
            with pytest.raises(RunCapacityExhaustedError):
                async with slots.hold():
                    pass
            with pytest.raises(TimeoutError):
                await task
            async with slots.hold():
                assert slots.in_use == 1

        asyncio.run(exercise())

    def test_there_is_no_deadlock_when_every_slot_is_held(self) -> None:
        """A blocking limiter would hang here. This one returns promptly,
        which is the property the refusal policy buys."""
        slots = RunSlots(1)

        async def exercise() -> None:
            async with slots.hold():
                # A generous timeout: if the refusal ever became a wait, this
                # would fail loudly rather than hanging the suite.
                async with asyncio.timeout(5):
                    with pytest.raises(RunCapacityExhaustedError):
                        async with slots.hold():
                            pass

        asyncio.run(exercise())


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_the_limiter_is_shared_across_requests_for_one_limit(self) -> None:
        """The defect this phase fixes, asserted directly: a per-request
        limiter counts to one and enforces nothing."""
        slots_for_limit.cache_clear()
        try:
            assert slots_for_limit(4) is slots_for_limit(4)
        finally:
            slots_for_limit.cache_clear()

    def test_different_limits_get_different_limiters(self) -> None:
        slots_for_limit.cache_clear()
        try:
            assert slots_for_limit(2) is not slots_for_limit(3)
        finally:
            slots_for_limit.cache_clear()

    def test_the_limiter_reads_the_configured_maximum(self, settings: Any) -> None:
        slots_for_limit.cache_clear()
        try:
            slots = get_run_slots(settings)
            assert slots.limit == settings.pipeline_max_concurrent_runs
        finally:
            slots_for_limit.cache_clear()

    def test_the_configured_default_is_two(self, settings: Any) -> None:
        assert settings.pipeline_max_concurrent_runs == 2


class TestErrorContract:
    def test_the_refusal_is_a_pipeline_error(self) -> None:
        """So the single handler in `app/main.py` maps it, like every other
        domain failure in this project."""
        assert issubclass(RunCapacityExhaustedError, PipelineError)

    def test_the_refusal_records_the_stage(self) -> None:
        error = RunCapacityExhaustedError("full", limit=2, in_use=2)
        assert error.stage == "admission"

    def test_the_refusal_maps_to_service_unavailable(self) -> None:
        from app.main import _PIPELINE_STATUS

        assert _PIPELINE_STATUS[RunCapacityExhaustedError] == 503

    def test_the_message_says_the_run_was_not_started(self) -> None:
        """A client has to be able to tell a refusal from a failure, because
        one is worth retrying and the other is not."""
        slots = RunSlots(1)

        async def exercise() -> None:
            async with slots.hold():
                with pytest.raises(RunCapacityExhaustedError) as caught:
                    async with slots.hold():
                        pass
                message = str(caught.value)
                assert "was not started" in message
                assert "retry" in message

        asyncio.run(exercise())


# ---------------------------------------------------------------------------
# The engine's use of it
# ---------------------------------------------------------------------------


class _StubEngineBody:
    """Stands in for the engine's turn loop.

    The engine's admission wrapper is what is under test here, not the turn
    loop, so the loop is replaced by something whose timing a test controls.
    """

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0
        self.behaviour = "complete"

    async def __call__(self, run_id: uuid.UUID) -> str:
        self.calls += 1
        self.entered.set()
        if self.behaviour == "raise":
            raise RuntimeError("the turn loop blew up")
        if self.behaviour == "hang":
            await asyncio.sleep(3600)
        await self.release.wait()
        return f"done-{run_id}"


def _engine_with(slots: RunSlots | None, body: _StubEngineBody) -> Any:
    """A `RunEngine` whose execution body is the stub above.

    Built with `object.__new__` and the three attributes the admission wrapper
    reads, so the test exercises the real `_admitted` and the real
    `run_to_completion` without needing a database, a provider or a scenario.
    """
    from app.pipeline.engine import RunEngine

    engine = object.__new__(RunEngine)
    engine._slots = slots
    engine._holds_slot = False
    engine._execute = body  # type: ignore[method-assign]
    return engine


class TestEngineAdmission:
    def test_an_engine_without_a_limiter_is_unlimited(self) -> None:
        """A unit test driving one run should not have to think about
        admission control, so a direct caller gets no limiter by default."""
        body = _StubEngineBody()
        engine = _engine_with(None, body)

        async def exercise() -> None:
            body.release.set()
            for _ in range(5):
                await engine.run_to_completion(RUN_A)

        asyncio.run(exercise())
        assert body.calls == 5

    def test_the_engine_holds_a_slot_while_executing(self) -> None:
        slots = RunSlots(2)
        body = _StubEngineBody()
        engine = _engine_with(slots, body)

        async def exercise() -> None:
            task = asyncio.create_task(engine.run_to_completion(RUN_A))
            await body.entered.wait()
            assert slots.in_use == 1
            body.release.set()
            await task
            assert slots.in_use == 0

        asyncio.run(exercise())

    def test_the_engine_refuses_a_run_beyond_the_limit(self) -> None:
        slots = RunSlots(1)
        first_body = _StubEngineBody()
        second_body = _StubEngineBody()
        first = _engine_with(slots, first_body)
        second = _engine_with(slots, second_body)

        async def exercise() -> None:
            task = asyncio.create_task(first.run_to_completion(RUN_A))
            await first_body.entered.wait()

            with pytest.raises(RunCapacityExhaustedError):
                await second.run_to_completion(RUN_B)
            # The refused run never reached its turn loop, which is what makes
            # the refusal safe to retry: nothing was executed.
            assert second_body.calls == 0

            first_body.release.set()
            await task

        asyncio.run(exercise())

    def test_a_refused_run_succeeds_once_capacity_frees_up(self) -> None:
        slots = RunSlots(1)
        first_body = _StubEngineBody()
        second_body = _StubEngineBody()
        first = _engine_with(slots, first_body)
        second = _engine_with(slots, second_body)

        async def exercise() -> None:
            task = asyncio.create_task(first.run_to_completion(RUN_A))
            await first_body.entered.wait()
            with pytest.raises(RunCapacityExhaustedError):
                await second.run_to_completion(RUN_B)

            first_body.release.set()
            await task

            second_body.release.set()
            assert await second.run_to_completion(RUN_B) == f"done-{RUN_B}"

        asyncio.run(exercise())
        assert slots.peak_in_use == 1

    def test_an_exception_in_the_turn_loop_releases_the_slot(self) -> None:
        slots = RunSlots(1)
        body = _StubEngineBody()
        body.behaviour = "raise"
        engine = _engine_with(slots, body)

        async def exercise() -> None:
            with pytest.raises(RuntimeError):
                await engine.run_to_completion(RUN_A)
            assert slots.in_use == 0
            assert engine._holds_slot is False

            other = _engine_with(slots, _StubEngineBody())
            other._execute.release.set()
            await other.run_to_completion(RUN_B)

        asyncio.run(exercise())

    def test_cancelling_a_run_releases_the_slot(self) -> None:
        slots = RunSlots(1)
        body = _StubEngineBody()
        body.behaviour = "hang"
        engine = _engine_with(slots, body)

        async def exercise() -> None:
            task = asyncio.create_task(engine.run_to_completion(RUN_A))
            await body.entered.wait()
            assert slots.in_use == 1

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert slots.in_use == 0

            other = _engine_with(slots, _StubEngineBody())
            other._execute.release.set()
            assert await other.run_to_completion(RUN_C) == f"done-{RUN_C}"

        asyncio.run(exercise())

    def test_a_timeout_releases_the_slot(self) -> None:
        """The engine's own run timeout is handled inside `_execute`; this
        covers an outer timeout unwinding through the admission frame, which
        is the case a `finally` has to catch."""
        slots = RunSlots(1)
        body = _StubEngineBody()
        body.behaviour = "hang"
        engine = _engine_with(slots, body)

        async def exercise() -> None:
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.02):
                    await engine.run_to_completion(RUN_A)
            assert slots.in_use == 0

            other = _engine_with(slots, _StubEngineBody())
            other._execute.release.set()
            await other.run_to_completion(RUN_B)

        asyncio.run(exercise())

    def test_supplying_bot_audio_does_not_refuse_itself(self) -> None:
        """The re-entrancy case. `supply_bot_audio` holds a slot and then calls
        `run_to_completion`, which would be refused by its own slot without
        the `_holds_slot` guard - a self-inflicted 503 under no load."""
        slots = RunSlots(1)
        engine = _engine_with(slots, _StubEngineBody())
        engine._execute.release.set()

        async def exercise() -> None:
            async with engine._admitted(RUN_A):
                assert slots.in_use == 1
                # The nested admission must be a no-op, not a refusal.
                async with engine._admitted(RUN_A):
                    assert slots.in_use == 1
                await engine.run_to_completion(RUN_A)
                assert slots.in_use == 1
            assert slots.in_use == 0

        asyncio.run(exercise())

    def test_nested_admission_does_not_release_early(self) -> None:
        """The other half of re-entrancy: the inner block must not give the
        slot back when it exits, or the outer block runs unprotected."""
        slots = RunSlots(1)
        engine = _engine_with(slots, _StubEngineBody())

        async def exercise() -> None:
            async with engine._admitted(RUN_A):
                async with engine._admitted(RUN_A):
                    pass
                assert slots.in_use == 1
                assert engine._holds_slot is True
            assert slots.in_use == 0
            assert engine._holds_slot is False

        asyncio.run(exercise())

    def test_two_overlapping_engines_never_exceed_the_limit(self) -> None:
        slots = RunSlots(2)
        bodies = [_StubEngineBody() for _ in range(4)]
        engines = [_engine_with(slots, body) for body in bodies]

        async def drive(index: int) -> str:
            try:
                return await engines[index].run_to_completion(RUN_A)
            except RunCapacityExhaustedError:
                return "refused"

        async def exercise() -> list[str]:
            tasks = [asyncio.create_task(drive(n)) for n in range(4)]
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            for body in bodies:
                body.release.set()
            return await asyncio.gather(*tasks)

        results = asyncio.run(exercise())
        assert slots.peak_in_use == 2
        assert results.count("refused") == 2
        assert slots.in_use == 0


class TestModesUnaffected:
    def test_the_implemented_modes_are_unchanged(self) -> None:
        """A regression guard: admission control must not quietly change what
        a run may be created as."""
        assert ExecutionMode.TELEPHONY_TEST.value == "telephony_test"
        from app.pipeline.modes import IMPLEMENTED_MODES

        assert ExecutionMode.TELEPHONY_TEST not in IMPLEMENTED_MODES
        assert len(IMPLEMENTED_MODES) == 3
