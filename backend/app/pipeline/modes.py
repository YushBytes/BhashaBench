"""What kind of test a run is, how far it has got, and how it ended.

Three separate enumerations, deliberately. Conflating them is how a report
comes to say an offline simulation was a voice-bot test.

`ExecutionMode` is the honesty control for the whole phase. Every run records
one, every report repeats it, and nothing infers it - the mode is chosen when
the run is created and the engine refuses to proceed if the configuration does
not match it. A run that never contacted an external bot cannot be labelled
`EXTERNAL_BOT_TEST`, because the adapter that would have contacted one is the
thing that sets the mode's requirements.
"""

from __future__ import annotations

from enum import StrEnum

from app.models.test_run import RunStatus


class ExecutionMode(StrEnum):
    """How a run obtains the bot's side of the conversation."""

    OFFLINE_SIMULATION = "offline_simulation"
    """No audio at all: bot replies are supplied as text.

    The Phase 6 path. Cheapest, fastest, and the only mode that needs neither a
    speech provider nor a credential. It proves the caller's logic and nothing
    about audio.
    """

    AUDIO_FIXTURE_TEST = "audio_fixture_test"
    """Real audio end to end, with the bot's replies read from fixtures.

    Caller text is synthesised, optionally degraded, stored, and the "bot's"
    reply is a pre-recorded or generated audio file which is then transcribed.
    Every stage of the pipeline runs for real except the bot, so this is what
    exercises synthesis, degradation, storage and transcription together.
    It establishes nothing about any particular voice bot.
    """

    EXTERNAL_BOT_TEST = "external_bot_test"
    """Caller audio was sent to a bot outside this process and its audio came back.

    The only mode that may be described as testing a bot. It requires an
    adapter that actually returns bot audio; the engine records the adapter's
    name and whether each reply was genuinely received.
    """

    TELEPHONY_TEST = "telephony_test"
    """A real phone call.

    **Not implemented.** Declared so that the vocabulary exists and Phase 8 has
    a value to fill rather than a value to add, and so that nothing else can be
    mistaken for it. Creating a run in this mode is refused.
    """


IMPLEMENTED_MODES: frozenset[ExecutionMode] = frozenset(
    {
        ExecutionMode.OFFLINE_SIMULATION,
        ExecutionMode.AUDIO_FIXTURE_TEST,
        ExecutionMode.EXTERNAL_BOT_TEST,
    }
)
"""Modes a run may actually be created in.

`TELEPHONY_TEST` is absent because no telephony exists. An enum member that
cannot be used is better than a missing one: it makes the gap explicit at the
point someone looks for it.
"""


class PipelineStatus(StrEnum):
    """How far a run has got.

    Finer-grained than `RunStatus`, which the database column uses. Both are
    kept: the column stays the coarse, constrained lifecycle Phase 2 defined,
    and this is recorded alongside it so a report can distinguish "timed out"
    from "failed" without a migration that would have to widen a CHECK
    constraint. `to_run_status` is the single place the mapping lives.
    """

    CREATED = "created"
    INITIALIZING = "initializing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL_STATUSES: frozenset[PipelineStatus] = frozenset(
    {
        PipelineStatus.COMPLETED,
        PipelineStatus.FAILED,
        PipelineStatus.CANCELLED,
        PipelineStatus.TIMED_OUT,
    }
)


_TO_RUN_STATUS: dict[PipelineStatus, RunStatus] = {
    # Nothing has started, which is exactly what the column's `pending` means.
    PipelineStatus.CREATED: RunStatus.PENDING,
    PipelineStatus.INITIALIZING: RunStatus.PENDING,
    PipelineStatus.RUNNING: RunStatus.RUNNING,
    PipelineStatus.COMPLETED: RunStatus.COMPLETED,
    PipelineStatus.FAILED: RunStatus.FAILED,
    PipelineStatus.CANCELLED: RunStatus.CANCELLED,
    # A timeout *is* a failure at the database's level of detail. The precise
    # status survives in `run_metadata`, so no information is lost - and the
    # alternative, adding a value, would mean editing the
    # `finished_at_matches_status` CHECK constraint that enumerates the
    # terminal three.
    PipelineStatus.TIMED_OUT: RunStatus.FAILED,
}


def to_run_status(status: PipelineStatus) -> RunStatus:
    """The `test_runs.status` value for a pipeline status."""
    return _TO_RUN_STATUS[status]


def is_terminal(status: PipelineStatus) -> bool:
    """Whether no further work will happen on a run in this status."""
    return status in TERMINAL_STATUSES


class RunOutcome(StrEnum):
    """Why a run ended.

    Separate from the status because "failed" is not a finding. A bot that
    refused, a bot that could not be understood and a provider that fell over
    are three different results, and a bench that reported one word for all
    three would be useless for the only purpose it has.
    """

    GOAL_ACHIEVED = "goal_achieved"
    BOT_REFUSED = "bot_refused"
    BOT_UNINTELLIGIBLE = "bot_unintelligible"
    NO_PROGRESS = "no_progress"
    TURN_BUDGET_EXHAUSTED = "turn_budget_exhausted"
    PROVIDER_ERROR = "provider_error"
    """Our side broke: synthesis or transcription failed in a way the run could
    not continue past. Never a statement about the bot."""
    AUDIO_VALIDATION_FAILED = "audio_validation_failed"
    EXTERNAL_BOT_UNAVAILABLE = "external_bot_unavailable"
    CANCELLED = "cancelled"


SUCCESS_OUTCOMES: frozenset[RunOutcome] = frozenset({RunOutcome.GOAL_ACHIEVED})
"""The only outcome that counts as the caller having achieved its objective.

A frozenset of one, named, so that a later phase adding a partial-success
outcome has one place to put it rather than a scattering of `== GOAL_ACHIEVED`
comparisons.
"""

OUR_FAULT_OUTCOMES: frozenset[RunOutcome] = frozenset(
    {
        RunOutcome.PROVIDER_ERROR,
        RunOutcome.AUDIO_VALIDATION_FAILED,
        RunOutcome.EXTERNAL_BOT_UNAVAILABLE,
    }
)
"""Outcomes that say nothing about the bot under test.

Aggregating these into a bot's score would blame it for our outage. Phase 10
should exclude them from any quality metric; the set exists now so that
decision is recorded where the outcomes are defined.
"""


__all__ = [
    "IMPLEMENTED_MODES",
    "OUR_FAULT_OUTCOMES",
    "SUCCESS_OUTCOMES",
    "TERMINAL_STATUSES",
    "ExecutionMode",
    "PipelineStatus",
    "RunOutcome",
    "is_terminal",
    "to_run_status",
]
