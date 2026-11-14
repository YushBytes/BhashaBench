"""HTTP request and response models for the test-run endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.caller.schemas import TerminationReason
from app.caller.state import CallerState
from app.pipeline.degradation import NoiseProfile
from app.pipeline.modes import ExecutionMode, PipelineStatus, RunOutcome


class CreateRunRequest(BaseModel):
    """Open a test run for one scenario."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "suite_id": "8f14e45f-ceea-467a-9d2e-1a3b4c5d6e7f",
                "scenario_id": "3f6c1e8a-2b7d-4a19-9c21-5f0d8e6b4a73",
                "mode": "audio_fixture_test",
                "noise_profile": "moderate_background_noise",
                "seed": 42,
            }
        }
    )

    suite_id: uuid.UUID = Field(description="Suite the run belongs to.")
    scenario_id: uuid.UUID = Field(description="Scenario the run will execute.")
    mode: ExecutionMode = Field(
        default=ExecutionMode.OFFLINE_SIMULATION,
        description="How the bot's side is obtained. `telephony_test` is "
        "refused: no telephony exists, and a mode that cannot run must not be "
        "creatable. Defaults to the offline mode, which needs no provider.",
    )
    noise_profile: NoiseProfile | None = Field(
        default=None,
        description="Degradation profile. Omit to use the scenario's own "
        "declared acoustic environment, which is part of the test's definition.",
    )
    seed: int | None = Field(
        default=None,
        description="Seed for anything stochastic in the degradation. Omit to "
        "use the configured default, which is fixed so a run is reproducible.",
    )
    max_turns: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Ceiling on caller turns, applied on top of the scenario's "
        "own `goal.max_turns` and the server limit. The lowest wins.",
    )
    degrade_caller_audio: bool = Field(
        default=True,
        description="Whether to degrade before sending. `false` sends the "
        "original - distinct from a `clean` profile, which is a deliberate "
        "choice of condition rather than a stage that did not run.",
    )
    bot_adapter: str | None = Field(
        default=None,
        description="Which bot adapter to use. Omit for the configured "
        "default, which sends audio nowhere.",
    )


class StageEventResponse(BaseModel):
    """One step of one turn, and what became of it."""

    turn_index: int = Field(ge=0)
    stage: str = Field(
        description="`caller_turn`, `caller_synthesis`, `degradation`, "
        "`bot_exchange`, `bot_audio_validation` or `bot_transcription`."
    )
    status: str = Field(description="`ok`, `failed`, `skipped` or `pending`.")
    duration_ms: float | None = Field(
        default=None, description="Measured, not estimated. `null` if not timed."
    )
    detail: str | None = Field(default=None, description="Redacted; never carries a credential.")


class ArtefactResponse(BaseModel):
    """One stored audio file."""

    turn_index: int = Field(ge=0)
    speaker: str
    variant: str | None = Field(
        default=None,
        description="`original` or `degraded`. Both are kept for a degraded "
        "turn, because a processed artefact is only evidence if the audio it "
        "came from is still there to compare against.",
    )
    reference: str = Field(
        description="Storage-root-relative path. Never an absolute filesystem "
        "path: that would disclose the server layout and be useless to a client."
    )
    size_bytes: int = Field(ge=0)
    content_type: str
    sample_rate_hz: int | None = Field(
        default=None, description="Read from the audio itself, never echoed from the request."
    )
    channels: int | None = None
    duration_seconds: float | None = Field(
        default=None, description="Only when it could be measured from the bytes."
    )
    derived_from: str | None = Field(
        default=None, description="The reference this was produced from."
    )
    transformations: list[str] = Field(default_factory=list)
    degradation_parameters: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None


class RunResponse(BaseModel):
    """A run's state and, once it has finished, its result."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "run_id": "1c9d4b2a-0e5f-4a7b-8c3d-2e1f0a9b8c7d",
                "mode": "audio_fixture_test",
                "status": "completed",
                "outcome": "goal_achieved",
                "caller_turns": 4,
                "bot_turns": 3,
                "bot_audio_externally_received": False,
            }
        }
    )

    run_id: uuid.UUID
    conversation_id: uuid.UUID | None
    scenario_name: str
    language: str
    mode: ExecutionMode
    status: PipelineStatus = Field(
        description="`created`, `initializing`, `running`, `completed`, "
        "`failed`, `cancelled` or `timed_out`."
    )
    outcome: RunOutcome | None = Field(
        default=None,
        description="`null` while the run is unfinished. An unfinished run has "
        "no result, and reporting one would be a fabricated figure.",
    )
    caller_provider: str
    uses_language_model: bool = Field(
        description="Whether a learned model generated the caller's words. "
        "**False throughout** - the caller is a rule engine, not Gnani Evon."
    )
    stt_provider: str | None
    tts_provider: str | None
    bot_adapter: str
    bot_audio_externally_received: bool = Field(
        description="True only if **every** bot reply came from outside this "
        "process. False for a fixture run, so an `external_bot_test` whose "
        "replies were fixtures can be seen to be mislabelled."
    )
    noise_profile: NoiseProfile
    scenario_noise_profile: str | None = Field(
        default=None,
        description="The acoustic environment the scenario declared. Recorded "
        "beside the profile applied, because the engine applies a noise "
        "severity rather than recreating an environment.",
    )
    degradation_seed: int | None
    caller_turns: int = Field(ge=0)
    bot_turns: int = Field(ge=0)
    bot_transcripts_succeeded: int = Field(ge=0)
    bot_transcripts_failed: int = Field(ge=0)
    turn_budget: int = Field(ge=0)
    caller_state: CallerState
    termination_reason: TerminationReason | None = None
    goal_achieved: bool
    total_audio_seconds: float = Field(
        ge=0,
        description="Summed duration of every artefact whose length could be "
        "measured. Containers this project cannot inspect contribute nothing "
        "rather than a guess.",
    )
    settings_not_enforced: list[SettingNotEnforcedResponse] | None = Field(
        default=None,
        description="Scenario settings this run declares that nothing in it "
        "enforces - interruptions, silence handling, phrase checks, and caller "
        "style the deterministic caller ignores. `null` for runs created before "
        "this was recorded, which means unknown, not fully enforced.",
    )
    degradation_requested: DegradationRequestedResponse | None = Field(
        default=None,
        description="The SNR and packet loss requested for each degraded turn. "
        "`null` for runs that move no audio and for runs created before this was recorded.",
    )
    awaiting_bot_text_for_turn: int | None = Field(
        default=None,
        description="Set when an `offline_simulation` run with the manual adapter "
        "is waiting for the bot's reply as text (`POST /bot-text`). The run is "
        "healthy, not failed.",
    )
    awaiting_bot_audio_for_turn: int | None = Field(
        default=None,
        description="Set when the run is waiting for an operator to supply the "
        "bot's reply. The run is healthy, not failed.",
    )
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


class RunTurnResponse(BaseModel):
    """One persisted utterance of a run's conversation."""

    index: int = Field(ge=0)
    speaker: str
    text: str | None = Field(
        default=None,
        description="`null` for a bot turn whose audio could not be "
        "transcribed - deliberately distinct from an empty string, which means "
        "the bot said nothing.",
    )
    intent: str | None = None
    state_before: str | None = None
    state_after: str | None = None
    rule_ids: list[str] = Field(default_factory=list)
    audio_reference: str | None = None
    transcription_error: str | None = None
    synthesis_error: str | None = None


class RunTurnsResponse(BaseModel):
    """Every turn of a run, in order."""

    run_id: uuid.UUID
    turns: list[RunTurnResponse]


class RunArtefactsResponse(BaseModel):
    """Every audio artefact a run produced."""

    run_id: uuid.UUID
    artefacts: list[ArtefactResponse]
    total_audio_seconds: float = Field(ge=0)


class RunReportResponse(BaseModel):
    """A run's full evidence: state, artefacts and every stage that ran."""

    run: RunResponse
    state_transitions: list[dict[str, Any]] = Field(
        description="The caller's state machine, turn by turn."
    )
    artefacts: list[ArtefactResponse]
    events: list[StageEventResponse]
    measurement_note: str = Field(
        default=(
            "Factual measurements only. This phase records counts, durations, "
            "sample rates, state transitions and stage outcomes. It computes no "
            "accuracy score, no word error rate and no semantic judgement: "
            "none of those is possible without a reviewed reference transcript, "
            "and evaluation is a later phase."
        ),
        description="Stated on the API surface so a consumer cannot mistake "
        "these counts for a quality score.",
    )


class SettingNotEnforcedResponse(BaseModel):
    """One scenario setting the run declares and nothing in it enforces."""

    setting: str = Field(
        description="Dotted path in the scenario, e.g. `constraints.allow_interruptions`."
    )
    declared: Any = Field(description="The value the scenario declares.")
    reason: str = Field(description="Why it was not enforced, and which phase would.")


class DegradationRequestedResponse(BaseModel):
    """What each degraded caller turn was asked for, and on whose authority.

    Requested, not achieved: every degraded artefact carries the measured
    `snr_db_achieved` and `packet_loss_realised_percent` beside these.
    """

    source: Literal["scenario", "operator"] = Field(
        description="`scenario`: the scenario's declared SNR and packet loss. "
        "`operator`: an explicit noise profile chosen for the run, applied as "
        "its reviewed preset."
    )
    snr_db: float | None = Field(
        description="Target signal-to-noise ratio. `null` when no noise is requested."
    )
    packet_loss_percent: float = Field(ge=0.0, le=100.0)


class BotTextRequest(BaseModel):
    """The bot's reply as text, for an offline run with the manual adapter."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        max_length=2000,
        description="What the bot said. An empty string records that the bot "
        "said nothing, which is a finding about the bot, not a malformed request.",
    )


class BotTextResponse(BaseModel):
    """What happened after an operator supplied the bot's reply as text."""

    run: RunResponse
    turn_index: int = Field(ge=0, description="The turn this reply answered.")


class BotAudioResponse(BaseModel):
    """What happened after an operator supplied the bot's reply."""

    run: RunResponse
    accepted_bytes: int = Field(ge=0)
    turn_index: int = Field(ge=0, description="The turn this reply answered.")


class BotAdapterResponse(BaseModel):
    """What one bot adapter can do."""

    name: str
    display_name: str
    selected: bool
    contacts_external_system: bool = Field(
        description="Whether using this adapter causes a request to leave this "
        "process. False for every adapter in this phase."
    )
    supports_sessions: bool
    requires_credentials: bool
    accepts_containers: list[str]
    notes: list[str] = Field(description="Honest limitations.")


class BotAdapterListResponse(BaseModel):
    """Every registered bot adapter."""

    selected: str
    adapters: list[BotAdapterResponse]
    telephony_status: str = Field(
        default=(
            "Not implemented. No telephony or SIP integration exists, so a run "
            "cannot be created in telephony_test mode. Real phone calls are a "
            "later phase."
        ),
        description="Stated on the API surface, not only in the documentation.",
    )
    execution_modes: list[str] = Field(
        default_factory=list,
        description="Modes a run may actually be created in.",
    )


class RunSummary(BaseModel):
    """One row of the run listing.

    A deliberate subset of `RunResponse`: what a history table shows without
    opening a run. Assembling a full report per row would mean loading every
    run's conversation, artefacts and stage events to render a line of text.

    Every field here is read from the run row or its stored pipeline
    metadata. Nothing is derived, inferred or defaulted into looking better
    than it is - `outcome` stays null while a run is unfinished, and
    `duration_seconds` stays null until there is both a start and a finish to
    measure between.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "run_id": "1c9d4b2a-0e5f-4a7b-8c3d-2e1f0a9b8c7d",
                "suite_id": "8f14e45f-ceea-467a-9d2e-1a3b4c5d6e7f",
                "scenario_name": "Hindi appointment booking",
                "language": "hi-IN",
                "mode": "audio_fixture_test",
                "status": "completed",
                "outcome": "goal_achieved",
                "caller_turns": 4,
                "bot_turns": 3,
                "bot_audio_externally_received": False,
                "created_at": "2026-01-01T00:00:00Z",
                "duration_seconds": 12.4,
            }
        }
    )

    run_id: uuid.UUID
    suite_id: uuid.UUID
    scenario_name: str
    language: str
    mode: ExecutionMode
    status: PipelineStatus
    outcome: RunOutcome | None = Field(
        default=None,
        description="Null while the run is unfinished. An unfinished run has no result.",
    )
    noise_profile: str | None = Field(
        default=None, description="Degradation profile applied to the caller's audio."
    )
    bot_adapter: str | None = Field(default=None, description="Adapter that supplied bot audio.")
    bot_audio_externally_received: bool = Field(
        default=False,
        description=(
            "True only if **every** bot reply came from outside this process. "
            "False for a fixture run, so a mislabelled external_bot_test is "
            "visible in the listing without opening it."
        ),
    )
    uses_language_model: bool = Field(
        default=False,
        description=(
            "Whether a learned model generated the caller's words. **False "
            "throughout** - the caller is a rule engine."
        ),
    )
    caller_turns: int = 0
    bot_turns: int = 0
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = Field(
        default=None,
        description=(
            "Wall-clock seconds between start and finish, measured from the "
            "two timestamps. Null for a run that has not finished - an "
            "elapsed-so-far figure in the same column would read as a "
            "duration and would not be one."
        ),
    )
    error: str | None = Field(default=None, description="Failure message, when the run failed.")


__all__ = [
    "ArtefactResponse",
    "BotAdapterListResponse",
    "BotAdapterResponse",
    "BotAudioResponse",
    "CreateRunRequest",
    "RunArtefactsResponse",
    "RunReportResponse",
    "RunResponse",
    "RunSummary",
    "RunTurnResponse",
    "RunTurnsResponse",
    "StageEventResponse",
]
