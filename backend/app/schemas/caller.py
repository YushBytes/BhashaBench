"""HTTP request and response models for the caller endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.caller.schemas import CallerIntent, TerminationReason
from app.caller.state import CallerState

MAX_BOT_TEXT_CHARS = 4000
"""Longest bot utterance accepted as text.

A bot turn is one utterance. Four thousand characters is far more than any
utterance and still bounds the request, which is the point - §13 asks for
limits, and an unbounded text field is the same exposure as an unbounded
upload, just cheaper to send.
"""


class StartConversationRequest(BaseModel):
    """Open a conversation for one scenario."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "suite_id": "8f14e45f-ceea-467a-9d2e-1a3b4c5d6e7f",
                "scenario_id": "3f6c1e8a-2b7d-4a19-9c21-5f0d8e6b4a73",
            }
        }
    )

    suite_id: uuid.UUID = Field(
        description="Suite the conversation's run belongs to. Required because "
        "`CallSession` hangs off a `TestRun`, which hangs off a suite."
    )
    scenario_id: uuid.UUID = Field(description="Scenario the caller will enact.")


class BotTextRequest(BaseModel):
    """Supply the bot's reply as text, skipping transcription."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"text": "Could you please confirm your claim reference number?"}
        }
    )

    text: str = Field(
        min_length=1,
        max_length=MAX_BOT_TEXT_CHARS,
        description="What the bot said. Use this when driving the conversation "
        "from text; submit audio to `/bot-audio` to go through transcription.",
    )


class TurnResponse(BaseModel):
    """One persisted utterance."""

    index: int = Field(ge=0)
    speaker: str
    text: str | None = Field(
        default=None,
        description="The utterance. `null` for a bot turn whose audio could not "
        "be transcribed - which is deliberately distinct from an empty string.",
    )
    intent: CallerIntent | None = Field(default=None, description="Caller turns only.")
    state_before: CallerState | None = None
    state_after: CallerState | None = None
    rule_ids: list[str] = Field(default_factory=list)
    explanation: str | None = Field(
        default=None,
        description="One line on why the caller chose this turn. A decision "
        "record, not a reasoning trace.",
    )
    facts_used: list[str] = Field(
        default_factory=list, description="Known-fact keys quoted in this turn."
    )
    audio_reference: str | None = Field(
        default=None,
        description="Storage-root-relative path to this turn's audio, when it "
        "was synthesised. Never an absolute filesystem path.",
    )
    audio_duration_seconds: float | None = Field(
        default=None, description="Only when it was verified from the audio itself."
    )
    transcription_error: str | None = None
    synthesis_error: str | None = None
    uses_language_model: bool | None = Field(
        default=None,
        description="Caller turns only: whether a language model produced the "
        "words of this turn. False for a turn the rule engine supplied, "
        "including one it supplied after a model failed.",
    )
    generation: dict[str, Any] | None = Field(
        default=None,
        description="How a model-backed provider produced this turn: provider, "
        "exact model, parameters, seed, tokens, latency, estimated cost, every "
        "attempt, and whether and why the rule engine took over. `null` for "
        "bot turns and for a conversation driven by the rule engine alone. A "
        "field the provider did not report is `null`, never a default.",
    )


class ConversationResponse(BaseModel):
    """A conversation's current state."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "conversation_id": "1c9d4b2a-0e5f-4a7b-8c3d-2e1f0a9b8c7d",
                "scenario_name": "tamil_crop_insurance_status",
                "language": "ta-IN",
                "provider": "deterministic",
                "uses_language_model": False,
                "state": "awaiting_information",
                "outcome": "in_progress",
                "turns_used": 2,
                "turn_budget": 14,
                "goal_achieved": False,
            }
        }
    )

    conversation_id: uuid.UUID
    scenario_name: str
    language: str
    provider: str
    uses_language_model: bool = Field(
        description=(
            "Whether a language model actually generated at least one of the "
            "caller's turns. Derived from each turn's execution record, not from "
            "which provider was configured: a conversation whose every model turn "
            "fell back to the rule engine reports `false`. Never Gnani Evon - no "
            "Evon provider exists."
        )
    )
    state: CallerState
    outcome: str = Field(description="`success`, `failure`, `aborted` or `in_progress`.")
    termination_reason: TerminationReason | None = None
    turns_used: int = Field(ge=0)
    turn_budget: int = Field(ge=0)
    goal_achieved: bool
    outcomes_expected: list[str] = Field(
        description="The scenario's expected outcomes. Returned here because "
        "this is a report surface; the caller itself never sees them."
    )
    outcomes_observed: list[str] = Field(
        description="Expected outcomes whose text appeared in the bot's "
        "transcripts. A keyword indicator, not a score - evaluation is Phase 11."
    )
    rule_ids_fired: list[str] = Field(default_factory=list)
    error: str | None = None
    llm: dict[str, Any] | None = Field(
        default=None,
        description="Totals across the conversation's model-backed turns: "
        "`turns_generated`, `turns_fallback`, `requests_sent`, `input_tokens`, "
        "`output_tokens`, `estimated_cost`, `currency`, `models` and "
        "`contacts_external_service`. `null` when no model-backed provider was "
        "asked for a turn. A token total is `null` when no turn reported one; "
        "an estimated cost is the worst case wherever usage was not reported. "
        "When `contacts_external_service` is false the figures are simulated.",
    )


class ConversationTurnsResponse(BaseModel):
    """Every turn of one conversation, in order."""

    conversation_id: uuid.UUID
    turns: list[TurnResponse]


class CallerProviderResponse(BaseModel):
    """What one caller provider can do."""

    name: str
    display_name: str
    selected: bool
    available: bool
    unavailable_reason: str | None = None
    is_deterministic: bool = Field(
        description="True when the same context always yields the same turn, "
        "which is what makes a benchmark reproducible."
    )
    uses_language_model: bool = Field(
        description="Whether this provider generates turns with a language model. "
        "What a given conversation actually used is reported on the conversation."
    )
    languages: list[str] = Field(
        description="Languages with phrase tables a fluent speaker has reviewed. "
        "A scenario in a language in neither list is refused rather than "
        "answered in English."
    )
    unreviewed_languages: list[str] = Field(
        default_factory=list,
        description="Languages the caller can speak from phrase tables no fluent "
        "speaker has reviewed. Runnable; each run records "
        "`caller_phrase_review: unreviewed` so its results carry the caveat.",
    )
    supports_code_mixing: bool
    requires_credentials: bool
    max_turns_supported: int | None = None
    notes: list[str] = Field(description="Honest limitations.")


class CallerProviderListResponse(BaseModel):
    """Every registered caller provider."""

    selected: str
    providers: list[CallerProviderResponse]
    evon_status: str = Field(
        default=(
            "Not implemented. Gnani Evon integration is deferred until "
            "documented API access and credentials are available: no "
            "text-generation endpoint is published and the released model has "
            "no hosted inference provider."
        ),
        description="Stated on the API surface, not only in the documentation, "
        "so a client cannot mistake the deterministic caller for Evon.",
    )


__all__ = [
    "MAX_BOT_TEXT_CHARS",
    "BotTextRequest",
    "CallerProviderListResponse",
    "CallerProviderResponse",
    "ConversationResponse",
    "ConversationTurnsResponse",
    "StartConversationRequest",
    "TurnResponse",
]
