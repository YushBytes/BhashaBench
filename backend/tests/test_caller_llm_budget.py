"""The live-spending controls: the authorisation gate and the durable budget.

Nothing here contacts anything. The ledger is exercised against a temporary
file, and the gate is asserted in the state the repository ships in: closed.
"""

from __future__ import annotations

import json
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from app.caller.llm import budget as live_budget
from app.caller.llm.budget import (
    HARD_LIVE_BUDGET_INR,
    LiveBudget,
    require_live_calls,
    shared_budget,
)
from app.caller.llm.errors import BudgetExceededError, LiveCallsDisabledError


def ledger(tmp_path: Path, ceiling: str = "10") -> LiveBudget:
    return LiveBudget(tmp_path / "ledger.json", ceiling=Decimal(ceiling), provider="test")


class TestTheLiveGate:
    def test_live_calls_are_not_authorised_in_this_repository(self) -> None:
        """The owner approved a budget, not live testing. This assertion is
        meant to fail the day someone flips the constant, so that the change
        cannot be made without also editing a test that says why."""
        assert live_budget.LIVE_CALLS_AUTHORISED is False

    @pytest.mark.parametrize("enabled", [False, True])
    def test_no_configuration_value_opens_it(self, enabled: bool) -> None:
        with pytest.raises(LiveCallsDisabledError, match="not authorised"):
            require_live_calls(enabled_in_configuration=enabled, provider="sarvam")

    def test_the_refusal_says_nothing_was_sent(self) -> None:
        with pytest.raises(LiveCallsDisabledError) as caught:
            require_live_calls(enabled_in_configuration=True, provider="sarvam")
        assert caught.value.request_sent is False
        assert caught.value.retryable is False
        assert caught.value.code == "live_calls_disabled"

    def test_authorised_but_switched_off_is_still_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(live_budget, "LIVE_CALLS_AUTHORISED", True)
        with pytest.raises(LiveCallsDisabledError, match="CALLER_LLM_LIVE_CALLS_ENABLED"):
            require_live_calls(enabled_in_configuration=False, provider="sarvam")

    def test_both_conditions_together_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(live_budget, "LIVE_CALLS_AUTHORISED", True)
        require_live_calls(enabled_in_configuration=True, provider="sarvam")


class TestTheCeiling:
    def test_the_hard_maximum_is_one_hundred_rupees(self) -> None:
        assert Decimal(100) == HARD_LIVE_BUDGET_INR

    def test_configuration_cannot_raise_it(self, tmp_path: Path) -> None:
        assert ledger(tmp_path, "5000").ceiling == Decimal(100)

    def test_configuration_can_lower_it(self, tmp_path: Path) -> None:
        assert ledger(tmp_path, "2.50").ceiling == Decimal("2.50")

    def test_a_zero_budget_refuses_everything(self, tmp_path: Path) -> None:
        with pytest.raises(BudgetExceededError):
            ledger(tmp_path, "0").reserve(Decimal("0.000001"), currency="INR")

    def test_a_negative_ceiling_is_a_programming_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="negative"):
            ledger(tmp_path, "-1")


class TestReserving:
    def test_a_new_ledger_has_spent_nothing(self, tmp_path: Path) -> None:
        budget = ledger(tmp_path)
        assert budget.committed() == Decimal(0)
        assert budget.remaining() == Decimal(10)

    def test_a_reservation_is_committed_before_anything_is_sent(self, tmp_path: Path) -> None:
        budget = ledger(tmp_path)
        budget.reserve(Decimal("1.25"), currency="INR")
        assert budget.committed() == Decimal("1.25")

    def test_reservations_accumulate_to_exactly_the_ceiling(self, tmp_path: Path) -> None:
        budget = ledger(tmp_path, "1")
        for _ in range(4):
            budget.reserve(Decimal("0.25"), currency="INR")
        assert budget.remaining() == Decimal(0)
        with pytest.raises(BudgetExceededError, match="already committed"):
            budget.reserve(Decimal("0.000001"), currency="INR")

    def test_a_refused_reservation_commits_nothing(self, tmp_path: Path) -> None:
        budget = ledger(tmp_path, "1")
        budget.reserve(Decimal("0.9"), currency="INR")
        with pytest.raises(BudgetExceededError):
            budget.reserve(Decimal("0.2"), currency="INR")
        assert budget.committed() == Decimal("0.9")

    def test_the_refusal_is_local_and_not_retryable(self, tmp_path: Path) -> None:
        with pytest.raises(BudgetExceededError) as caught:
            ledger(tmp_path, "1").reserve(Decimal(2), currency="INR")
        assert caught.value.request_sent is False
        assert caught.value.retryable is False

    @pytest.mark.parametrize("amount", ["0", "-1"])
    def test_a_cost_of_nothing_is_an_unknown_cost(self, tmp_path: Path, amount: str) -> None:
        with pytest.raises(BudgetExceededError, match="not treated as zero"):
            ledger(tmp_path).reserve(Decimal(amount), currency="INR")

    def test_another_currency_cannot_be_compared(self, tmp_path: Path) -> None:
        with pytest.raises(BudgetExceededError, match="USD"):
            ledger(tmp_path).reserve(Decimal("0.01"), currency="USD")


class TestSettling:
    def test_reported_usage_replaces_the_worst_case(self, tmp_path: Path) -> None:
        budget = ledger(tmp_path)
        reservation = budget.reserve(Decimal("0.50"), currency="INR")
        budget.settle(reservation, Decimal("0.02"))
        assert budget.committed() == Decimal("0.02")

    def test_an_unknown_cost_keeps_the_worst_case(self, tmp_path: Path) -> None:
        budget = ledger(tmp_path)
        reservation = budget.reserve(Decimal("0.50"), currency="INR")
        budget.settle(reservation, None)
        assert budget.committed() == Decimal("0.50")

    def test_an_unsettled_reservation_stays_charged(self, tmp_path: Path) -> None:
        """What a timeout, a cancellation or a crash leaves behind."""
        ledger(tmp_path).reserve(Decimal("0.50"), currency="INR")
        assert ledger(tmp_path).committed() == Decimal("0.50")

    def test_a_cost_above_the_reservation_is_recorded_in_full(self, tmp_path: Path) -> None:
        budget = ledger(tmp_path)
        reservation = budget.reserve(Decimal("0.10"), currency="INR")
        budget.settle(reservation, Decimal("0.30"))
        assert budget.committed() == Decimal("0.30")

    def test_settling_only_touches_its_own_reservation(self, tmp_path: Path) -> None:
        budget = ledger(tmp_path)
        budget.reserve(Decimal(1), currency="INR")
        second = budget.reserve(Decimal(2), currency="INR")
        budget.settle(second, Decimal("0.5"))
        assert budget.committed() == Decimal("1.5")

    def test_a_negative_actual_is_a_programming_error(self, tmp_path: Path) -> None:
        budget = ledger(tmp_path)
        reservation = budget.reserve(Decimal(1), currency="INR")
        with pytest.raises(ValueError, match="negative"):
            budget.settle(reservation, Decimal(-1))


class TestDurability:
    def test_spending_survives_a_restart(self, tmp_path: Path) -> None:
        ledger(tmp_path, "1").reserve(Decimal("0.8"), currency="INR")
        with pytest.raises(BudgetExceededError):
            ledger(tmp_path, "1").reserve(Decimal("0.3"), currency="INR")

    def test_the_file_records_the_total_and_no_secret(self, tmp_path: Path) -> None:
        budget = ledger(tmp_path)
        budget.reserve(Decimal("0.75"), currency="INR")
        document = json.loads(budget.path.read_text(encoding="utf-8"))
        assert document == {
            "version": 1,
            "currency": "INR",
            "committed": "0.75",
            "ceiling": "10",
        }

    @pytest.mark.parametrize(
        "content",
        [
            "not json",
            "[]",
            "{}",
            '{"currency": "INR", "committed": "lots"}',
            '{"currency": "INR", "committed": "-3"}',
            '{"currency": "INR", "committed": "NaN"}',
            '{"currency": "USD", "committed": "1"}',
        ],
    )
    def test_an_unreadable_ledger_refuses_rather_than_reading_as_zero(
        self, tmp_path: Path, content: str
    ) -> None:
        budget = ledger(tmp_path)
        budget.path.write_text(content, encoding="utf-8")
        with pytest.raises(BudgetExceededError, match="could not be read"):
            budget.reserve(Decimal("0.01"), currency="INR")
        assert budget.path.read_text(encoding="utf-8") == content

    def test_a_held_lock_refuses_rather_than_spending_unlocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(live_budget, "_LOCK_ATTEMPTS", 2)
        monkeypatch.setattr(live_budget, "_LOCK_WAIT_SECONDS", 0)
        budget = ledger(tmp_path)
        (tmp_path / "ledger.json.lock").write_text("", encoding="utf-8")
        with pytest.raises(BudgetExceededError, match="locked by another process"):
            budget.reserve(Decimal("0.01"), currency="INR")

    def test_the_lock_is_released_after_every_operation(self, tmp_path: Path) -> None:
        budget = ledger(tmp_path, "1")
        with pytest.raises(BudgetExceededError):
            budget.reserve(Decimal(5), currency="INR")
        assert not (tmp_path / "ledger.json.lock").exists()

    def test_concurrent_reservations_cannot_overspend(self, tmp_path: Path) -> None:
        budget = ledger(tmp_path, "1")
        granted: list[int] = []

        def worker() -> None:
            try:
                budget.reserve(Decimal("0.1"), currency="INR")
            except BudgetExceededError:
                return
            granted.append(1)

        threads = [threading.Thread(target=worker) for _ in range(25)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(granted) == 10
        assert budget.committed() == Decimal("1.0")


class TestTheSharedLedger:
    def test_one_instance_per_file(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.json"
        assert shared_budget(path, Decimal(5), "sarvam") is shared_budget(
            path, Decimal(5), "sarvam"
        )
