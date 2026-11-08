"""The caller's conversation state machine.

An explicit transition table rather than scattered `if` statements, for one
reason: every transition has to be testable in isolation and provable
exhaustive. A state machine expressed as control flow inside a provider cannot
be enumerated, so nobody can tell whether a path exists that never terminates.

`ALLOWED` is that enumeration. `is_terminal` is the only thing the orchestrator
needs to ask to know whether to stop, and `TERMINAL` is reachable from every
non-terminal state, which is what makes a runaway conversation impossible by
construction rather than by a turn counter alone.
"""

from __future__ import annotations

from enum import StrEnum


class CallerState(StrEnum):
    """Where the caller believes the conversation has got to.

    Deliberately about the *caller's* progress toward its objective, not about
    the telephony call - `CallSession.status` already covers that, and
    conflating the two would mean a caller that had achieved its goal could not
    be distinguished from a call that had merely connected.
    """

    INITIAL = "initial"
    """Nothing said yet. The caller has not opened."""

    INTRODUCING = "introducing"
    """The caller has stated who they are and what they want."""

    AWAITING_INFORMATION = "awaiting_information"
    """The caller has asked its question and is waiting for a useful answer."""

    PROVIDING_DETAILS = "providing_details"
    """The bot asked for something - a reference number, a name - and the
    caller is supplying it from the scenario's known facts."""

    SEEKING_CLARIFICATION = "seeking_clarification"
    """The bot's last answer was unusable: unclear, contradictory, or about
    something else. The caller is pressing for a usable one."""

    CONFIRMING = "confirming"
    """The caller has what it came for and is reading it back to check."""

    GOAL_ACHIEVED = "goal_achieved"
    """Terminal, success: every expected outcome was observed."""

    FAILED = "failed"
    """Terminal, failure: the turn budget ran out, or the bot refused, or the
    caller could not make progress."""

    TERMINATED = "terminated"
    """Terminal, neither: something outside the conversation stopped it - a
    provider failure, a cancellation, an operator ending the session."""


TERMINAL: frozenset[CallerState] = frozenset(
    {CallerState.GOAL_ACHIEVED, CallerState.FAILED, CallerState.TERMINATED}
)
"""States from which no further caller turn is produced.

Three of them rather than one, because "finished" is not a single outcome: a
benchmark has to tell a scenario that succeeded from one the bot failed from
one that never got a fair trial. Collapsing them would make a provider outage
look like a bot defect.
"""


ALLOWED: dict[CallerState, frozenset[CallerState]] = {
    CallerState.INITIAL: frozenset(
        {CallerState.INTRODUCING, CallerState.FAILED, CallerState.TERMINATED}
    ),
    CallerState.INTRODUCING: frozenset(
        {
            CallerState.AWAITING_INFORMATION,
            CallerState.PROVIDING_DETAILS,
            CallerState.SEEKING_CLARIFICATION,
            # A bot can answer the objective in its first reply - a helpline
            # that recognises the caller's number does exactly that - and the
            # caller's right move is then to read the detail back. Omitting
            # CONFIRMING here would reject that turn and kill the conversation
            # on the best thing a bot can do.
            CallerState.CONFIRMING,
            CallerState.GOAL_ACHIEVED,
            CallerState.FAILED,
            CallerState.TERMINATED,
        }
    ),
    CallerState.AWAITING_INFORMATION: frozenset(
        {
            CallerState.AWAITING_INFORMATION,
            CallerState.PROVIDING_DETAILS,
            CallerState.SEEKING_CLARIFICATION,
            CallerState.CONFIRMING,
            CallerState.GOAL_ACHIEVED,
            CallerState.FAILED,
            CallerState.TERMINATED,
        }
    ),
    CallerState.PROVIDING_DETAILS: frozenset(
        {
            CallerState.AWAITING_INFORMATION,
            CallerState.PROVIDING_DETAILS,
            CallerState.SEEKING_CLARIFICATION,
            CallerState.CONFIRMING,
            CallerState.GOAL_ACHIEVED,
            CallerState.FAILED,
            CallerState.TERMINATED,
        }
    ),
    CallerState.SEEKING_CLARIFICATION: frozenset(
        {
            CallerState.AWAITING_INFORMATION,
            CallerState.PROVIDING_DETAILS,
            CallerState.SEEKING_CLARIFICATION,
            CallerState.CONFIRMING,
            CallerState.GOAL_ACHIEVED,
            CallerState.FAILED,
            CallerState.TERMINATED,
        }
    ),
    CallerState.CONFIRMING: frozenset(
        {
            CallerState.SEEKING_CLARIFICATION,
            CallerState.GOAL_ACHIEVED,
            CallerState.FAILED,
            CallerState.TERMINATED,
        }
    ),
    # Terminal states have no outgoing transitions. Declared explicitly rather
    # than omitted, so `ALLOWED` covers every member of the enum and a new
    # state cannot be added without deciding where it can go.
    CallerState.GOAL_ACHIEVED: frozenset(),
    CallerState.FAILED: frozenset(),
    CallerState.TERMINATED: frozenset(),
}
"""Every transition the caller is permitted to make.

Self-transitions are allowed for the three working states - a caller can ask
again, supply another detail, or clarify a second time - and the turn budget,
not the state machine, is what stops that repeating forever. `CONFIRMING`
deliberately cannot loop back to asking: once the caller is reading an answer
back, the next step is either agreement or a clarification, and a caller that
could slide from confirming to asking again would never settle.
"""


def is_terminal(state: CallerState) -> bool:
    """Whether the conversation has finished."""
    return state in TERMINAL


def can_transition(source: CallerState, target: CallerState) -> bool:
    """Whether `source` -> `target` is a permitted move."""
    return target in ALLOWED.get(source, frozenset())


def outcome_of(state: CallerState) -> str:
    """Describe a terminal state in benchmark terms.

    Raises:
        ValueError: `state` is not terminal. Asking for the outcome of a live
            conversation is a bug in the caller, not a value to invent.
    """
    if state is CallerState.GOAL_ACHIEVED:
        return "success"
    if state is CallerState.FAILED:
        return "failure"
    if state is CallerState.TERMINATED:
        return "aborted"
    raise ValueError(f"{state} is not a terminal state")


__all__ = [
    "ALLOWED",
    "TERMINAL",
    "CallerState",
    "can_transition",
    "is_terminal",
    "outcome_of",
]
