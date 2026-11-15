"""The caller domain's own models: what a provider is given, what it returns.

Deliberately separate from `app.schemas.scenario_spec`. A provider receives a
*projection* of a scenario, not the scenario itself, and the difference is the
point of §9's integrity rules: `expected_outcomes` is how BhashaBench decides
whether the bot passed, so handing it to the thing that talks to the bot would
let the caller read out the marking scheme. `CallerContext` carries what a real
caller would plausibly know and nothing else.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.caller.state import CallerState


class Speaker(StrEnum):
    """Who produced an utterance. Mirrors `app.models.conversation_turn.Speaker`."""

    CALLER = "caller"
    BOT = "bot"


class CallerIntent(StrEnum):
    """What the caller is trying to do with this utterance.

    A closed set rather than free text, so a report can count intents across a
    run and a test can assert on one.
    """

    OPEN = "open"
    """State who is calling and why."""
    ASK = "ask"
    """Ask the question the scenario exists to ask."""
    PROVIDE_FACT = "provide_fact"
    """Supply a known fact the bot asked for."""
    CLARIFY = "clarify"
    """Press for a usable answer."""
    REPEAT_REQUEST = "repeat_request"
    """Ask the bot to say it again."""
    CORRECT = "correct"
    """Tell the bot it got a detail wrong."""
    DECLINE_UNKNOWN = "decline_unknown"
    """Say truthfully that the caller does not know something."""
    CONFIRM = "confirm"
    """Read the answer back to check it."""
    CLOSE = "close"
    """End the call politely."""


class TerminationReason(StrEnum):
    """Why a conversation stopped. Only these; a provider cannot invent one."""

    GOAL_ACHIEVED = "goal_achieved"
    TURN_BUDGET_EXHAUSTED = "turn_budget_exhausted"
    BOT_REFUSED = "bot_refused"
    NO_PROGRESS = "no_progress"
    BOT_UNINTELLIGIBLE = "bot_unintelligible"
    PROVIDER_ERROR = "provider_error"
    OPERATOR_TERMINATED = "operator_terminated"
    CANCELLED = "cancelled"


class CallerPersona(BaseModel):
    """Who the caller is, projected from the scenario's persona block."""

    model_config = ConfigDict(frozen=True)

    identity: str = Field(description="Who the caller is, e.g. 'Smallholder farmer'.")
    speaking_style: str = Field(description="Scenario `speaking_style` value.")
    traits: tuple[str, ...] = Field(default=(), description="Behavioural traits.")
    language: str = Field(description="BhashaBench language tag the caller speaks.")
    secondary_language: str | None = Field(
        default=None,
        description="Second language when the scenario declares code-mixing; "
        "`None` for a monolingual caller.",
    )
    code_mixing_expected: bool = Field(
        default=False, description="Whether the scenario expects mixed speech."
    )
    switch_triggers: tuple[str, ...] = Field(
        default=(),
        description="Scenario `switch_triggers` - when mixing is expected to occur.",
    )


class ConversationTurnView(BaseModel):
    """One past utterance, as a provider sees it."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    speaker: Speaker
    text: str
    intent: CallerIntent | None = Field(
        default=None, description="Set for caller turns; `None` for bot turns."
    )


class CallerResourceUse(BaseModel):
    """What this conversation's caller has already consumed.

    Carried in the context so a provider can refuse to exceed a per-run limit
    without reaching into the database. It is accounting, not prompt material:
    nothing here is ever shown to a model.
    """

    model_config = ConfigDict(frozen=True)

    llm_requests: int = Field(default=0, ge=0, description="Model requests sent so far.")
    estimated_cost: str = Field(
        default="0",
        description="Decimal string. The sum of each request's cost estimate, "
        "which is the worst case wherever the provider reported no usage.",
    )
    currency: str | None = Field(
        default=None, description="ISO 4217 code, when anything was spent."
    )


class CallerContext(BaseModel):
    """Everything a provider is given to decide one turn.

    **What is deliberately absent:** `expected_outcomes`. Those are the marking
    criteria, and a caller that could see them could recite them at the bot -
    which would make every scenario pass. Outcome checking happens in the
    orchestrator, against the transcript, after the caller has spoken.
    """

    model_config = ConfigDict(frozen=True)

    scenario_id: str = Field(description="Scenario primary key, for correlation.")
    scenario_name: str
    objective: str = Field(description="The caller's aim, from `goal.objective`.")
    persona: CallerPersona
    known_facts: dict[str, str] = Field(
        default_factory=dict,
        description="Facts the caller genuinely knows. The ONLY source of "
        "concrete detail a provider may put in an utterance.",
    )
    history: tuple[ConversationTurnView, ...] = Field(
        default=(), description="Prior turns, oldest first."
    )
    bot_transcript: str | None = Field(
        default=None,
        description="What the bot last said, as transcribed. `None` on the "
        "opening turn; empty string when transcription produced no words.",
    )
    state: CallerState = Field(description="Caller state before this turn.")
    turn_index: int = Field(ge=0, description="Index this turn will occupy.")
    turns_remaining: int = Field(ge=0, description="Turns left in the budget, this one included.")
    resources: CallerResourceUse = Field(
        default_factory=CallerResourceUse,
        description="What the caller has already spent in this conversation.",
    )

    @property
    def is_opening(self) -> bool:
        """Whether this is the first thing the caller says."""
        return self.state is CallerState.INITIAL and not self.history

    @property
    def last_bot_text(self) -> str:
        """The bot's last utterance, or an empty string if there was none."""
        return self.bot_transcript or ""


class GenerationAttempt(BaseModel):
    """One request made while producing a turn, successful or not."""

    model_config = ConfigDict(frozen=True)

    attempt: int = Field(ge=1)
    outcome: str = Field(description="`ok`, or the failure's stable code.")
    error_type: str | None = None
    detail: str | None = Field(default=None, description="Redacted, one line.")
    latency_ms: float | None = None
    request_sent: bool = Field(
        description="Whether a request actually left the process. False when a "
        "limit or a disabled gate refused it first."
    )


class GenerationEvidence(BaseModel):
    """How one caller turn was actually produced.

    The record a claim about a run rests on. Every field is either what
    happened or `None`; nothing is defaulted to a plausible value. In
    particular `generated_by_language_model` is true only when the words that
    were spoken came out of a model and passed validation - a turn the
    deterministic caller supplied after a model failure records `False` here
    and says why in `fallback_reason`.
    """

    model_config = ConfigDict(frozen=True)

    provider: str = Field(description="The provider asked to generate the turn.")
    model: str | None = Field(description="Exact model identifier requested.")
    model_reported: str | None = Field(
        default=None, description="Model identifier the provider's response named, if any."
    )
    contacts_external_service: bool = Field(
        description="False for an offline double: its token counts and cost are "
        "simulated and must never be reported as spend."
    )
    prompt_version: str | None = None
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Generation parameters as sent. Never a credential.",
    )
    seed_requested: int | None = None
    seed_sent: bool = Field(
        default=False, description="Whether the seed was included in the request."
    )
    seed_honoured: bool | None = Field(
        default=None,
        description="`None` when the provider gives no way to tell, which is "
        "the case for a best-effort seed.",
    )
    system_fingerprint: str | None = None
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    latency_ms: float | None = Field(
        default=None, description="Wall time across every attempt for this turn."
    )
    estimated_cost: str | None = Field(
        default=None, description="Decimal string; `None` when nothing was sent."
    )
    currency: str | None = None
    cost_basis: str | None = Field(
        default=None,
        description="`reported_usage` when computed from the provider's token "
        "counts, `worst_case` when usage was missing and the upper bound was "
        "charged instead, `mixed` when attempts differed.",
    )
    attempts: tuple[GenerationAttempt, ...] = ()
    retry_count: int = Field(default=0, ge=0)
    fallback_used: bool = False
    fallback_reason: str | None = Field(
        default=None, description="Stable code; set exactly when `fallback_used`."
    )
    fallback_detail: str | None = None
    generated_by_language_model: bool = Field(
        description="Whether the spoken words were produced by a language model."
    )

    def model_post_init(self, _context: object) -> None:
        """A turn cannot be both model-generated and a fallback."""
        if self.fallback_used and self.generated_by_language_model:
            raise ValueError("a fallback turn was not generated by the language model")
        if self.fallback_used != (self.fallback_reason is not None):
            raise ValueError("fallback_reason must be set exactly when fallback_used is")


class CallerDecision(BaseModel):
    """What a provider decided to say, and what it believes follows.

    `explanation` and `rule_ids` are a short, machine-readable record of *why*
    - not a reasoning trace. §5 forbids storing hidden chain-of-thought, and
    for a rule engine the rule's identity is both sufficient and more useful:
    it is greppable, assertable in a test, and reportable across a run.
    """

    model_config = ConfigDict(frozen=True)

    message: str = Field(
        min_length=1,
        description="What the caller says. Non-empty by construction - an "
        "empty utterance must never reach speech synthesis.",
    )
    intent: CallerIntent
    next_state: CallerState
    goal_achieved: bool = Field(
        default=False, description="Whether the caller believes its aim is met."
    )
    should_terminate: bool = Field(
        default=False, description="Whether this is the caller's last turn."
    )
    termination_reason: TerminationReason | None = Field(
        default=None, description="Required when `should_terminate`; otherwise forbidden."
    )
    explanation: str = Field(
        description="One short line on why this turn was chosen. Not a reasoning trace."
    )
    rule_ids: tuple[str, ...] = Field(
        default=(), description="Identifiers of the rules that fired, in order."
    )
    facts_used: tuple[str, ...] = Field(
        default=(),
        description="Known-fact keys quoted in `message`. Lets the orchestrator "
        "verify that every concrete detail came from the scenario.",
    )
    generation: GenerationEvidence | None = Field(
        default=None,
        description="How this turn was produced, when a model-backed provider "
        "was asked for it. `None` for the rule engine, which has nothing to add "
        "beyond `rule_ids`.",
    )

    def model_post_init(self, _context: object) -> None:
        """Reject internally inconsistent decisions at construction.

        A decision that says "terminate" with no reason, or gives a reason
        while continuing, is a bug in a rule. Catching it here means it cannot
        reach the database or the report.
        """
        if self.should_terminate and self.termination_reason is None:
            raise ValueError("a terminating decision must carry a termination_reason")
        if not self.should_terminate and self.termination_reason is not None:
            raise ValueError(
                "termination_reason is set but should_terminate is False; "
                "a reason without a termination is contradictory"
            )
        if self.goal_achieved and self.next_state is not CallerState.GOAL_ACHIEVED:
            raise ValueError(
                f"goal_achieved is True but next_state is {self.next_state}; the two must agree"
            )
        if self.next_state is CallerState.GOAL_ACHIEVED and not self.goal_achieved:
            raise ValueError("next_state is GOAL_ACHIEVED but goal_achieved is False")


__all__ = [
    "CallerContext",
    "CallerDecision",
    "CallerIntent",
    "CallerPersona",
    "CallerResourceUse",
    "ConversationTurnView",
    "GenerationAttempt",
    "GenerationEvidence",
    "Speaker",
    "TerminationReason",
]
