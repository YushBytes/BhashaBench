"""The test-run engine: one scenario, many turns, audio all the way through.

This is the thing Phase 7 exists to build. It owns the run lifecycle and the
turn lifecycle, and it is deliberately free of FastAPI - the API module calls
it, the tests call it directly, and nothing here knows what an HTTP status is.

**It wraps Phase 6 rather than replacing it.** `ConversationOrchestrator`
already produces and persists caller turns, already transcribes bot audio
through Prisma with the right null-transcript semantics, and already owns the
caller state machine. Reimplementing any of that would mean two conversation
engines disagreeing eventually. So the engine's job is the audio legs that
Phase 6 has no opinion about:

    orchestrator.next_caller_turn()   <- Phase 6: decide + synthesise + persist
    read the original artefact back
    degrade it                        <- Phase 7
    store the degraded artefact       <- Phase 7
    adapter.send_turn(...)            <- Phase 7: hand it to the bot
    validate the reply's audio        <- Phase 7
    orchestrator.submit_bot_audio()   <- Phase 6: Prisma + persist

Reading the caller's audio back off disk rather than having Phase 6 hand the
bytes over is a deliberate small cost: it keeps `next_caller_turn`'s signature
and Phase 6's tests untouched, and the read is a local file.

**Every stage is recorded, including the ones that failed.** §6 forbids
silently skipping a step, so each turn appends an event with its stage, its
outcome and its measured duration. A run that broke at transcription and one
that broke at synthesis look different in the report, which is the only way
either is diagnosable.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.caller.artefacts import AudioArtefactStore
from app.caller.errors import (
    CallerError,
    ConversationNotActiveError,
    ScenarioNotUsableError,
)
from app.caller.orchestrator import ConversationOrchestrator
from app.caller.schemas import Speaker, TerminationReason
from app.caller.state import CallerState
from app.caller.state import is_terminal as caller_state_is_terminal
from app.core.config import Settings
from app.models.call_session import CallSession
from app.models.test_run import RunStatus, TestRun
from app.pipeline.bots.protocol import BotAdapter, BotReply
from app.pipeline.degradation import (
    NoiseProfile,
    degrade,
    profile_config,
)
from app.pipeline.errors import (
    BotAdapterError,
    BotAudioPendingError,
    DegradationError,
    PipelineConfigurationError,
    RunNotActiveError,
)
from app.pipeline.modes import (
    IMPLEMENTED_MODES,
    ExecutionMode,
    PipelineStatus,
    RunOutcome,
    is_terminal,
    to_run_status,
)
from app.repositories import caller_conversations as caller_repo
from app.repositories import pipeline_runs as repo
from app.schemas.scenario import ScenarioSpec
from app.services.errors import NotFoundError
from app.speech.errors import SpeechError
from app.transcription import audio as audio_tools
from app.transcription.errors import TranscriptionError
from app.transcription.models import AudioEncoding, AudioMetadata
from app.transcription.redaction import redact
from app.utils.timing import monotonic_seconds

logger = logging.getLogger("bhashabench.pipeline")

MAX_BOT_AUDIO_BYTES = 10 * 1024 * 1024
"""Largest bot reply the engine will accept, matching the caller endpoint."""

_ACCEPTED_BOT_AUDIO = frozenset(
    {AudioEncoding.WAV, AudioEncoding.MP3, AudioEncoding.OGG, AudioEncoding.FLAC}
)
"""Containers a bot reply may arrive in.

Narrower than everything Prisma accepts, because the degradation engine and
the WAV inspector can only measure some of these - and a reply whose duration
cannot be established is still usable for transcription, which is why the
compressed containers are permitted rather than refused.
"""

# A scenario names an acoustic *environment*; the engine applies a *severity*.
# Two different axes, and this is the one place they meet.
#
# `app/schemas/scenario_spec.py` defined these six names in Phase 2 with the
# note "Phase 7 implements these", so honouring them is part of this phase's
# job. The engine does not synthesise a market or a fan: it applies the noise
# severity that environment implies, over the telephony channel. Several
# environments therefore share a severity, which loses information - so the
# run records the scenario's declared environment *and* the profile applied,
# and the report shows both rather than implying the environment was recreated.
_SCENARIO_PROFILES: dict[str, NoiseProfile] = {
    "clean": NoiseProfile.CLEAN,
    "rural": NoiseProfile.LIGHT_BACKGROUND_NOISE,
    "indoor_fan": NoiseProfile.LIGHT_BACKGROUND_NOISE,
    "urban": NoiseProfile.MODERATE_BACKGROUND_NOISE,
    "market": NoiseProfile.HEAVY_BACKGROUND_NOISE,
    "worst_case": NoiseProfile.HEAVY_BACKGROUND_NOISE,
}


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Everything chosen when a run is created.

    Frozen, because a run's configuration is part of its evidence: a run whose
    profile changed halfway through would be unreproducible, and the report
    quotes these values as what produced the artefacts.
    """

    mode: ExecutionMode
    noise_profile: NoiseProfile = NoiseProfile.CLEAN
    seed: int | None = None
    bot_adapter: str = "scripted"
    max_turns: int | None = None
    """Ceiling on caller turns, on top of the scenario's and the settings'."""
    degrade_caller_audio: bool = True
    """Whether to degrade before sending. False keeps the original on the wire.

    Separate from the profile so `CLEAN` and "do not degrade" stay
    distinguishable: the first is a deliberate choice of condition, the second
    means the stage did not run.
    """

    def validate(self) -> None:
        """Reject a configuration the engine cannot honour.

        Raises:
            PipelineConfigurationError: unimplemented mode, or a mode whose
                requirements the rest of the configuration does not meet.
        """
        if self.mode not in IMPLEMENTED_MODES:
            raise PipelineConfigurationError(
                f"execution mode '{self.mode.value}' is not implemented. "
                f"Available modes are {sorted(m.value for m in IMPLEMENTED_MODES)}. "
                "Telephony arrives in Phase 8; a run cannot be created in that "
                "mode until it genuinely exists."
            )
        if self.max_turns is not None and self.max_turns < 1:
            raise PipelineConfigurationError(f"max_turns must be at least 1, got {self.max_turns}")

    @property
    def uses_audio(self) -> bool:
        """Whether this run moves audio at all."""
        return self.mode is not ExecutionMode.OFFLINE_SIMULATION


@dataclass(slots=True)
class StageEvent:
    """One step of one turn, and what became of it."""

    turn_index: int
    stage: str
    status: str
    """`ok`, `failed`, `skipped` or `pending`."""
    duration_ms: float | None = None
    detail: str | None = None
    """Redacted before it gets here. Never carries a credential."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "stage": self.stage,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ArtefactRecord:
    """One stored audio file, as the report should describe it."""

    turn_index: int
    speaker: str
    variant: str | None
    reference: str
    size_bytes: int
    content_type: str
    sample_rate_hz: int | None = None
    channels: int | None = None
    duration_seconds: float | None = None
    derived_from: str | None = None
    """The reference this was produced from, for a degraded artefact.

    What makes the original/processed pair legible after the fact: a reader can
    follow a degraded file back to the audio it came from.
    """
    transformations: tuple[str, ...] = field(default=())
    degradation_parameters: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "speaker": self.speaker,
            "variant": self.variant,
            "reference": self.reference,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
            "duration_seconds": self.duration_seconds,
            "derived_from": self.derived_from,
            "transformations": list(self.transformations),
            "degradation_parameters": self.degradation_parameters,
            "seed": self.seed,
        }


@dataclass(frozen=True, slots=True)
class RunReport:
    """The structured result of a run. Facts only.

    §11 is explicit that this phase measures and does not judge: there is no
    accuracy figure, no word error rate and no semantic score here, because
    none of those can be computed without a reviewed reference transcript.
    Everything below was either counted or measured.
    """

    run_id: uuid.UUID
    conversation_id: uuid.UUID | None
    scenario_name: str
    language: str
    mode: ExecutionMode
    status: PipelineStatus
    outcome: RunOutcome | None
    caller_provider: str
    uses_language_model: bool
    stt_provider: str | None
    tts_provider: str | None
    bot_adapter: str
    bot_audio_externally_received: bool
    """True only if every bot reply came from outside this process.

    The check that keeps `EXTERNAL_BOT_TEST` honest. A run in that mode whose
    replies were fixtures reports False here, and the mode claim can be seen to
    be wrong.
    """
    noise_profile: NoiseProfile
    scenario_noise_profile: str | None
    """The acoustic environment the scenario declared.

    Kept beside the profile actually applied, because the engine applies a
    noise *severity* rather than recreating an environment - flattening the two
    would imply a market was synthesised.
    """
    degradation_seed: int | None
    awaiting_bot_audio_for_turn: int | None
    """Set while the run is waiting for an operator to supply the bot's reply.

    A waiting run is healthy, so this is distinct from an error: it says which
    turn the stored caller audio belongs to.
    """
    caller_turns: int
    bot_turns: int
    bot_transcripts_succeeded: int
    bot_transcripts_failed: int
    turn_budget: int
    caller_state: CallerState
    termination_reason: TerminationReason | None
    goal_achieved: bool
    state_transitions: tuple[dict[str, Any], ...]
    artefacts: tuple[ArtefactRecord, ...]
    events: tuple[StageEvent, ...]
    started_at: str | None
    finished_at: str | None
    error: str | None = None

    @property
    def total_audio_seconds(self) -> float:
        """Summed duration of every artefact whose length could be measured.

        Measured, not estimated: an artefact in a container this project cannot
        inspect without a decoder contributes nothing rather than a guess.
        """
        return round(
            sum(a.duration_seconds or 0.0 for a in self.artefacts),
            3,
        )


class RunEngine:
    """Creates, advances and closes pipeline runs.

    Named `RunEngine` and not `TestRunEngine` deliberately: pytest collects any
    class whose name starts with `Test`, so the obvious name would make this
    class uncollectable-but-warned in every test module that imported it -
    the same trap CLAUDE.md records for the `TestRun` and `TestSuite` ORM
    classes, which cannot be renamed. This one could be, so it was.
    """

    def __init__(
        self,
        *,
        session: Session,
        orchestrator: ConversationOrchestrator,
        settings: Settings,
        bot_adapter: BotAdapter,
        artefacts: AudioArtefactStore,
        stt_provider: str | None = None,
        tts_provider: str | None = None,
    ) -> None:
        self._session = session
        self._orchestrator = orchestrator
        self._settings = settings
        self._bot = bot_adapter
        self._artefacts = artefacts
        # Passed in rather than discovered. The transcription service hangs off
        # the orchestrator privately and the speech service hangs off the
        # *caller* service inside it, so reading both would mean reaching
        # through two layers of other modules' internals. Whoever builds the
        # engine already knows these names.
        self._stt_provider = stt_provider
        self._tts_provider = tts_provider

    # -- Lifecycle ----------------------------------------------------------

    def create(
        self,
        *,
        suite_id: uuid.UUID,
        scenario_id: uuid.UUID,
        config: RunConfig,
    ) -> TestRun:
        """Open a run and its conversation.

        Delegates to `ConversationOrchestrator.start`, which creates both the
        `TestRun` and the `CallSession` and applies Phase 6's language check
        and turn budget. The pipeline then writes its own metadata onto the
        run - so there is exactly one place that knows how to start a
        conversation, and it is not here.

        Raises:
            PipelineConfigurationError: the configuration cannot be honoured.
            NotFoundError: no such scenario.
            ScenarioNotUsableError: the caller cannot speak the scenario's
                language.
        """
        config.validate()

        if config.uses_audio and self._stt_provider is None:
            raise PipelineConfigurationError(
                f"mode '{config.mode.value}' moves audio, so a transcription "
                "provider is required; none is configured"
            )
        if config.uses_audio and self._tts_provider is None:
            raise PipelineConfigurationError(
                f"mode '{config.mode.value}' moves audio, so a speech provider "
                "is required; none is configured"
            )

        conversation = self._orchestrator.start(suite_id=suite_id, scenario_id=scenario_id)
        run = repo.get_run(self._session, conversation.test_run_id)
        if run is None:  # pragma: no cover - just created in this transaction
            raise NotFoundError("TestRun", conversation.test_run_id)

        # Fetched explicitly rather than through `conversation.scenario`. The
        # relationship is `lazy="raise_on_sql"` and this `CallSession` was just
        # created rather than loaded, so the related row is only reachable
        # without SQL while it happens to sit in the identity map - which stops
        # being true the moment anything commits. That made this a bug that
        # only appeared behind the HTTP layer.
        scenario_row = caller_repo.get_scenario(self._session, scenario_id)
        if scenario_row is None:  # pragma: no cover - checked by start() above
            raise NotFoundError("Scenario", scenario_id)
        spec = ScenarioSpec.model_validate(scenario_row.spec)
        caller_meta = caller_repo.caller_metadata_of(conversation)
        profile = self._resolve_profile(config, spec)
        declared = getattr(spec.audio, "noise_profile", None)
        declared_name = str(getattr(declared, "value", declared) or "clean")
        budget = self._resolve_budget(config, caller_meta)

        # A narrower budget has to reach the caller, not just the engine's
        # loop. Phase 6's `budget.exhausted` rule is what produces a graceful
        # closing turn and a `TURN_BUDGET_EXHAUSTED` termination; without this
        # the caller would believe it had the scenario's full allowance and the
        # engine would have to cut it off mid-conversation, which reports no
        # outcome at all.
        if budget != int(caller_meta.get("turn_budget", budget)):
            caller_meta["turn_budget"] = budget
            caller_repo.update_caller_metadata(self._session, conversation, caller_meta)

        # Phase 6's `create_run` marks a run `running` with a start time,
        # because Phase 6 creates a run and uses it immediately. A pipeline run
        # is created and started separately, so a run nobody has started yet is
        # reset to pending here - "running since before it began" would be a
        # small lie in every row.
        run.status = RunStatus.PENDING
        run.started_at = None

        metadata: dict[str, Any] = {
            "status": PipelineStatus.CREATED.value,
            "mode": config.mode.value,
            "outcome": None,
            "conversation_id": str(conversation.id),
            "scenario_name": spec.name,
            "language": spec.language,
            "caller_provider": caller_meta.get("provider"),
            "uses_language_model": caller_meta.get("uses_language_model", False),
            "stt_provider": self._stt_provider if config.uses_audio else None,
            "tts_provider": self._tts_provider if config.uses_audio else None,
            "bot_adapter": self._bot.capabilities.name,
            "bot_contacts_external_system": self._bot.capabilities.contacts_external_system,
            "noise_profile": profile.value,
            "scenario_noise_profile": declared_name,
            "degrade_caller_audio": config.degrade_caller_audio and config.uses_audio,
            "degradation_seed": self._resolve_seed(config),
            "turn_budget": budget,
            "events": [],
            "artefacts": [],
            "state_transitions": [],
            # Starts True and is cleared by the first reply that did not come
            # from outside this process. An audio-fixture run therefore ends
            # with False, and cannot be described as an external bot test.
            "bot_audio_externally_received": config.uses_audio,
            "bot_transcripts_succeeded": 0,
            "bot_transcripts_failed": 0,
        }
        repo.update_pipeline_metadata(self._session, run, metadata)

        logger.info(
            "pipeline.run_created",
            extra={
                "run_id": str(run.id),
                "conversation_id": str(conversation.id),
                "mode": config.mode.value,
                "scenario": spec.name,
                "noise_profile": profile.value,
                "bot_adapter": self._bot.capabilities.name,
            },
        )
        return run

    def _resolve_profile(self, config: RunConfig, spec: ScenarioSpec) -> NoiseProfile:
        """The profile this run will use.

        An explicit `CLEAN` on the config does not override a scenario that
        asks for noise: a scenario's audio section is part of the test's
        definition, and silently running it clean would report a result for a
        condition that was never applied. So the scenario wins unless the
        config names something other than the default.
        """
        if config.noise_profile is not NoiseProfile.CLEAN:
            return config.noise_profile
        declared = getattr(spec.audio, "noise_profile", None)
        key = str(getattr(declared, "value", declared) or "clean")
        return _SCENARIO_PROFILES.get(key, NoiseProfile.CLEAN)

    def _resolve_seed(self, config: RunConfig) -> int | None:
        """The seed for anything stochastic in this run."""
        if not config.uses_audio:
            return None
        return config.seed if config.seed is not None else self._settings.pipeline_noise_seed

    def _resolve_budget(self, config: RunConfig, caller_meta: dict[str, Any]) -> int:
        """The effective turn budget: the lowest of every applicable limit."""
        budget = int(caller_meta.get("turn_budget", self._settings.caller_max_turns))
        if config.max_turns is not None:
            budget = min(budget, config.max_turns)
        return budget

    # -- Loading ------------------------------------------------------------

    def _load(self, run_id: uuid.UUID) -> tuple[TestRun, dict[str, Any]]:
        """Fetch a run and its pipeline metadata."""
        run = repo.get_run(self._session, run_id)
        if run is None:
            raise NotFoundError("TestRun", run_id)
        return run, repo.pipeline_metadata_of(run)

    def _load_active(self, run_id: uuid.UUID) -> tuple[TestRun, dict[str, Any]]:
        """Fetch a run and insist it has not finished."""
        run, meta = self._load(run_id)
        status = PipelineStatus(meta.get("status", PipelineStatus.CREATED.value))
        if is_terminal(status):
            raise RunNotActiveError(
                f"run {run_id} has already finished in status '{status.value}'; "
                "no further turns can be executed",
                run_id=str(run_id),
            )
        return run, meta

    def _conversation(self, run_id: uuid.UUID) -> CallSession:
        conversation = repo.conversation_of(self._session, run_id)
        if conversation is None:  # pragma: no cover - created with the run
            raise NotFoundError("Conversation for TestRun", run_id)
        return conversation

    # -- Execution ----------------------------------------------------------

    async def run_to_completion(self, run_id: uuid.UUID) -> RunReport:
        """Execute turns until the run reaches a terminal state.

        Bounded three ways, because one bound is never enough: the caller's own
        turn budget, this run's recorded budget, and a wall-clock timeout over
        the whole run. The loop also stops the moment a turn reports the
        conversation finished.

        A `BotAudioPendingError` is not a failure - it leaves the run `running`
        and returns, which is how the manual adapter's "waiting for the
        operator" state is expressed. The caller polls or posts audio.
        """
        run, meta = self._load_active(run_id)
        meta["status"] = PipelineStatus.INITIALIZING.value
        repo.mark_running(self._session, run, meta)

        budget = int(meta.get("turn_budget", self._settings.caller_max_turns))
        timeout = self._settings.pipeline_run_timeout_seconds

        try:
            async with asyncio.timeout(timeout):
                # `budget` iterations, not `budget + 1`: each produces one
                # caller turn, and one more would exceed the budget the report
                # quotes. The caller normally closes itself before this bound
                # via its own `budget.exhausted` rule.
                for _ in range(budget):
                    run, meta = self._load(run_id)
                    status = PipelineStatus(meta.get("status", PipelineStatus.CREATED.value))
                    if is_terminal(status):
                        break
                    advanced = await self._advance_once(run_id)
                    if not advanced:
                        # Waiting for externally supplied audio. Healthy.
                        break
                else:
                    # The loop ran its full course without the caller closing.
                    # Finish the run rather than leaving it `running` forever
                    # with no outcome - an unfinished run is not a result.
                    run, meta = self._load(run_id)
                    if not is_terminal(
                        PipelineStatus(meta.get("status", PipelineStatus.CREATED.value))
                    ):
                        self._finish(
                            run,
                            meta,
                            status=PipelineStatus.COMPLETED,
                            outcome=RunOutcome.TURN_BUDGET_EXHAUSTED,
                        )
        except TimeoutError:
            run, meta = self._load(run_id)
            self._finish(
                run,
                meta,
                status=PipelineStatus.TIMED_OUT,
                outcome=RunOutcome.PROVIDER_ERROR,
                error=f"the run exceeded its {timeout} second budget",
            )

        return self.report(run_id)

    async def _advance_once(self, run_id: uuid.UUID) -> bool:
        """Execute one caller turn and one bot reply.

        Returns False when the run is waiting for audio that has to arrive from
        outside, True otherwise.
        """
        run, meta = self._load_active(run_id)
        meta["status"] = PipelineStatus.RUNNING.value
        conversation = self._conversation(run_id)
        events: list[dict[str, Any]] = list(meta.get("events", []))
        artefacts: list[dict[str, Any]] = list(meta.get("artefacts", []))
        transitions: list[dict[str, Any]] = list(meta.get("state_transitions", []))

        turn_index = caller_repo.next_turn_index(self._session, conversation.id)
        config_mode = ExecutionMode(meta["mode"])

        # -- Caller leg: decide, and (for audio modes) synthesise -----------
        started = monotonic_seconds()
        try:
            await self._orchestrator.next_caller_turn(conversation.id)
        except ConversationNotActiveError:
            # The caller finished on its previous turn. Not an error.
            self._close_from_caller(run, meta, conversation, events, artefacts, transitions)
            return False
        except SpeechError as exc:
            events.append(
                StageEvent(
                    turn_index=turn_index,
                    stage="caller_synthesis",
                    status="failed",
                    duration_ms=_elapsed(started),
                    detail=f"{type(exc).__name__}: {redact(exc)}",
                ).as_dict()
            )
            meta["events"] = events
            self._finish(
                run,
                meta,
                status=PipelineStatus.FAILED,
                outcome=RunOutcome.PROVIDER_ERROR,
                error=f"speech synthesis failed: {redact(exc)}",
            )
            return False
        except CallerError as exc:
            events.append(
                StageEvent(
                    turn_index=turn_index,
                    stage="caller_decision",
                    status="failed",
                    duration_ms=_elapsed(started),
                    detail=f"{type(exc).__name__}: {redact(exc)}",
                ).as_dict()
            )
            meta["events"] = events
            self._finish(
                run,
                meta,
                status=PipelineStatus.FAILED,
                outcome=RunOutcome.PROVIDER_ERROR,
                error=f"the caller could not produce a turn: {redact(exc)}",
            )
            return False

        events.append(
            StageEvent(
                turn_index=turn_index,
                stage="caller_turn",
                status="ok",
                duration_ms=_elapsed(started),
            ).as_dict()
        )

        self._session.expire_all()
        conversation = self._conversation(run_id)
        caller_turn = _turn_at(conversation, turn_index)
        caller_meta = (caller_turn.turn_metadata or {}) if caller_turn is not None else {}
        transitions.append(
            {
                "turn_index": turn_index,
                "speaker": Speaker.CALLER.value,
                "state_before": caller_meta.get("state_before"),
                "state_after": caller_meta.get("state_after"),
                "intent": caller_meta.get("intent"),
                "rule_ids": caller_meta.get("rule_ids", []),
            }
        )

        # A synthesis failure that Phase 6 swallowed into the turn metadata is
        # still a failed stage here: the pipeline cannot send audio it does not
        # have, and recording the turn as fine would be the silent skip §6
        # forbids.
        if caller_meta.get("synthesis_error"):
            events.append(
                StageEvent(
                    turn_index=turn_index,
                    stage="caller_synthesis",
                    status="failed",
                    detail=str(caller_meta["synthesis_error"]),
                ).as_dict()
            )

        caller_state = CallerState(
            caller_repo.caller_metadata_of(conversation).get("state", CallerState.INITIAL.value)
        )

        # -- Bot leg --------------------------------------------------------
        if config_mode is ExecutionMode.OFFLINE_SIMULATION:
            meta["events"] = events
            meta["artefacts"] = artefacts
            meta["state_transitions"] = transitions
            repo.update_pipeline_metadata(self._session, run, meta)
            if caller_state_is_terminal(caller_state):
                run, meta = self._load(run_id)
                self._close_from_caller(run, meta, conversation, events, artefacts, transitions)
            return False

        if caller_state_is_terminal(caller_state):
            meta["events"] = events
            meta["artefacts"] = artefacts
            meta["state_transitions"] = transitions
            self._close_from_caller(run, meta, conversation, events, artefacts, transitions)
            return False

        outcome = await self._audio_exchange(
            run=run,
            meta=meta,
            conversation=conversation,
            turn_index=turn_index,
            caller_meta=caller_meta,
            events=events,
            artefacts=artefacts,
            transitions=transitions,
        )
        return outcome

    async def _audio_exchange(
        self,
        *,
        run: TestRun,
        meta: dict[str, Any],
        conversation: CallSession,
        turn_index: int,
        caller_meta: dict[str, Any],
        events: list[dict[str, Any]],
        artefacts: list[dict[str, Any]],
        transitions: list[dict[str, Any]],
    ) -> bool:
        """Degrade the caller's audio, send it, and transcribe the reply."""
        run_id = run.id
        audio_meta = caller_meta.get("audio") or {}
        reference = audio_meta.get("reference")

        if not reference:
            meta["events"] = events
            self._finish(
                run,
                meta,
                status=PipelineStatus.FAILED,
                outcome=RunOutcome.PROVIDER_ERROR,
                error=(
                    "the caller's turn produced no audio artefact, so there is "
                    "nothing to send to the bot; check that caller synthesis is "
                    "enabled and that the speech provider is configured"
                ),
            )
            return False

        original = self._artefacts.read(str(reference))
        artefacts.append(
            ArtefactRecord(
                turn_index=turn_index,
                speaker=Speaker.CALLER.value,
                variant="original",
                reference=str(reference),
                size_bytes=int(audio_meta.get("size_bytes") or len(original)),
                content_type=str(audio_meta.get("content_type") or "audio/wav"),
                sample_rate_hz=audio_meta.get("sample_rate_hz"),
                duration_seconds=audio_meta.get("duration_seconds"),
            ).as_dict()
        )

        # -- Degradation ----------------------------------------------------
        outbound = original
        outbound_reference = str(reference)
        if meta.get("degrade_caller_audio"):
            started = monotonic_seconds()
            try:
                config = profile_config(
                    NoiseProfile(meta["noise_profile"]), seed=meta.get("degradation_seed")
                )
                result = degrade(original, config)
            except DegradationError as exc:
                events.append(
                    StageEvent(
                        turn_index=turn_index,
                        stage="degradation",
                        status="failed",
                        duration_ms=_elapsed(started),
                        detail=f"{type(exc).__name__}: {exc}",
                    ).as_dict()
                )
                meta["events"] = events
                meta["artefacts"] = artefacts
                self._finish(
                    run,
                    meta,
                    status=PipelineStatus.FAILED,
                    outcome=RunOutcome.AUDIO_VALIDATION_FAILED,
                    error=f"audio degradation failed: {exc}",
                )
                return False

            if result.applied:
                stored = self._artefacts.write(
                    result.audio,
                    conversation_id=conversation.id,
                    turn_index=turn_index,
                    speaker=Speaker.CALLER,
                    container="wav",
                    content_type="audio/wav",
                    variant="degraded",
                )
                outbound = result.audio
                outbound_reference = stored.reference
                artefacts.append(
                    ArtefactRecord(
                        turn_index=turn_index,
                        speaker=Speaker.CALLER.value,
                        variant="degraded",
                        reference=stored.reference,
                        size_bytes=stored.size_bytes,
                        content_type=stored.content_type,
                        sample_rate_hz=result.output_sample_rate_hz,
                        channels=result.output_channels,
                        duration_seconds=round(result.output_duration_seconds, 3),
                        # The original is preserved and pointed at, which is
                        # what makes the pair verifiable after the fact.
                        derived_from=str(reference),
                        transformations=tuple(t.value for t in result.transformations),
                        degradation_parameters=dict(result.parameters),
                        seed=result.seed,
                    ).as_dict()
                )
            events.append(
                StageEvent(
                    turn_index=turn_index,
                    stage="degradation",
                    status="ok" if result.applied else "skipped",
                    duration_ms=_elapsed(started),
                    detail=(
                        None
                        if result.applied
                        else f"profile '{result.profile.value}' applies no transformation"
                    ),
                ).as_dict()
            )

        # -- Bot exchange ---------------------------------------------------
        started = monotonic_seconds()
        try:
            reply = await self._bot.send_turn(
                outbound,
                run_id=run_id,
                turn_index=turn_index,
                content_type="audio/wav",
                language=str(meta.get("language", "en-IN")),
                timeout_seconds=self._settings.caller_turn_timeout_seconds,
            )
        except BotAudioPendingError as exc:
            # Healthy: the run is waiting for an operator. Status stays
            # `running` and the stage is recorded as pending, not failed.
            events.append(
                StageEvent(
                    turn_index=turn_index,
                    stage="bot_exchange",
                    status="pending",
                    duration_ms=_elapsed(started),
                    detail=str(exc),
                ).as_dict()
            )
            meta["events"] = events
            meta["artefacts"] = artefacts
            meta["state_transitions"] = transitions
            meta["awaiting_bot_audio_for_turn"] = turn_index
            meta["awaiting_caller_artefact"] = outbound_reference
            repo.update_pipeline_metadata(self._session, run, meta)
            return False
        except BotAdapterError as exc:
            events.append(
                StageEvent(
                    turn_index=turn_index,
                    stage="bot_exchange",
                    status="failed",
                    duration_ms=_elapsed(started),
                    detail=f"{type(exc).__name__}: {redact(exc)}",
                ).as_dict()
            )
            meta["events"] = events
            meta["artefacts"] = artefacts
            self._finish(
                run,
                meta,
                status=PipelineStatus.FAILED,
                outcome=RunOutcome.EXTERNAL_BOT_UNAVAILABLE,
                error=f"the bot adapter failed: {redact(exc)}",
            )
            return False

        bot_latency = _elapsed(started)
        if not reply.received_from_bot:
            # One fixture reply is enough to make the whole run not an external
            # bot test. Cleared here rather than computed at report time so the
            # record cannot be re-derived more favourably later.
            meta["bot_audio_externally_received"] = False

        events.append(
            StageEvent(
                turn_index=turn_index,
                stage="bot_exchange",
                status="ok",
                duration_ms=reply.latency_ms if reply.latency_ms is not None else bot_latency,
                detail=f"adapter '{self._bot.capabilities.name}'",
            ).as_dict()
        )

        meta["events"] = events
        meta["artefacts"] = artefacts
        meta["state_transitions"] = transitions
        measured = self._validate_bot_audio(
            run=run, meta=meta, conversation=conversation, reply=reply, events=events
        )
        if measured is None:
            return False
        return await self._transcribe_reply(
            run_id=run_id,
            reply=reply,
            measured=measured,
            events=events,
            artefacts=artefacts,
        )

    def _validate_bot_audio(
        self,
        *,
        run: TestRun,
        meta: dict[str, Any],
        conversation: CallSession,
        reply: BotReply,
        events: list[dict[str, Any]],
    ) -> AudioMetadata | None:
        """Validate the bot's audio before anything else touches it.

        §6: invalid or incomplete audio must never be stored as a successful
        turn, so validation happens here and a failure ends the run with
        `AUDIO_VALIDATION_FAILED` - which is deliberately not a statement about
        the bot's behaviour.

        Returns the measured metadata, or `None` if the run was failed.
        """
        turn_index = caller_repo.next_turn_index(self._session, conversation.id)
        started = monotonic_seconds()
        try:
            metadata = audio_tools.validate(
                reply.audio,
                accepted=_ACCEPTED_BOT_AUDIO,
                max_bytes=MAX_BOT_AUDIO_BYTES,
            )
        except TranscriptionError as exc:
            # This family and only this family: `audio_tools.validate` raises
            # `InvalidAudioError`, `UnsupportedFormatError` or
            # `AudioTooLargeError`, all of which subclass it.
            events.append(
                StageEvent(
                    turn_index=turn_index,
                    stage="bot_audio_validation",
                    status="failed",
                    duration_ms=_elapsed(started),
                    detail=f"{type(exc).__name__}: {redact(exc)}",
                ).as_dict()
            )
            meta["events"] = events
            self._finish(
                run,
                meta,
                status=PipelineStatus.FAILED,
                outcome=RunOutcome.AUDIO_VALIDATION_FAILED,
                error=f"the bot's audio did not validate: {redact(exc)}",
            )
            return None

        events.append(
            StageEvent(
                turn_index=turn_index,
                stage="bot_audio_validation",
                status="ok",
                duration_ms=_elapsed(started),
                detail=f"{metadata.encoding.value}, {metadata.sample_rate_hz or 'unmeasured'} Hz",
            ).as_dict()
        )
        meta["events"] = events
        repo.update_pipeline_metadata(self._session, run, meta)
        return metadata

    async def _transcribe_reply(
        self,
        *,
        run_id: uuid.UUID,
        reply: BotReply,
        measured: AudioMetadata,
        events: list[dict[str, Any]],
        artefacts: list[dict[str, Any]],
    ) -> bool:
        """Hand the bot's audio to Phase 6, which transcribes and persists it.

        `submit_bot_audio` already stores the artefact, calls Prisma, and
        records a null-content turn with a `transcription_error` when the
        provider fails - which is why there is no transcription code here.
        """
        run, meta = self._load_active(run_id)
        conversation = self._conversation(run_id)
        turn_index = caller_repo.next_turn_index(self._session, conversation.id)

        started = monotonic_seconds()
        try:
            await self._orchestrator.submit_bot_audio(conversation.id, audio=reply.audio)
        except TranscriptionError as exc:
            # A request-shaped transcription failure that Phase 6 re-raises:
            # the audio was unusable rather than the provider being down.
            events.append(
                StageEvent(
                    turn_index=turn_index,
                    stage="bot_transcription",
                    status="failed",
                    duration_ms=_elapsed(started),
                    detail=f"{type(exc).__name__}: {redact(exc)}",
                ).as_dict()
            )
            meta["events"] = events
            self._finish(
                run,
                meta,
                status=PipelineStatus.FAILED,
                outcome=RunOutcome.AUDIO_VALIDATION_FAILED,
                error=f"the bot's audio could not be transcribed: {redact(exc)}",
            )
            return False
        except ScenarioNotUsableError as exc:
            meta["events"] = events
            self._finish(
                run,
                meta,
                status=PipelineStatus.FAILED,
                outcome=RunOutcome.PROVIDER_ERROR,
                error=redact(exc),
            )
            return False

        self._session.expire_all()
        conversation = self._conversation(run_id)
        bot_turn = _turn_at(conversation, turn_index)
        bot_meta = (bot_turn.turn_metadata or {}) if bot_turn is not None else {}
        audio_record = bot_meta.get("audio") or {}

        artefacts.append(
            ArtefactRecord(
                turn_index=turn_index,
                speaker=Speaker.BOT.value,
                variant="original",
                reference=str(audio_record.get("reference") or ""),
                size_bytes=int(audio_record.get("size_bytes") or reply.size_bytes),
                content_type=reply.content_type,
                sample_rate_hz=measured.sample_rate_hz,
                channels=measured.channels,
                duration_seconds=(
                    None
                    if measured.duration_seconds is None
                    else round(measured.duration_seconds, 3)
                ),
            ).as_dict()
        )

        failed = bot_meta.get("transcription_error")
        events.append(
            StageEvent(
                turn_index=turn_index,
                stage="bot_transcription",
                status="failed" if failed else "ok",
                duration_ms=_elapsed(started),
                detail=str(failed) if failed else None,
            ).as_dict()
        )
        key = "bot_transcripts_failed" if failed else "bot_transcripts_succeeded"
        meta[key] = int(meta.get(key, 0)) + 1
        meta["events"] = events
        meta["artefacts"] = artefacts
        meta.pop("awaiting_bot_audio_for_turn", None)
        meta.pop("awaiting_caller_artefact", None)
        repo.update_pipeline_metadata(self._session, run, meta)
        return True

    async def supply_bot_audio(
        self,
        run_id: uuid.UUID,
        *,
        audio: bytes,
        content_type: str = "audio/wav",
    ) -> RunReport:
        """Accept the bot's reply from outside and carry the run on.

        The resume half of the manual flow. `ManualBotAdapter` pauses a run by
        raising `BotAudioPendingError`; this is what un-pauses it, and it
        deliberately does **not** go back through the adapter - an adapter is
        built per request, so an in-memory one could not hold a reply between
        the request that stored the caller's audio and the request that answers
        it. The HTTP boundary is the transport here.

        The audio is recorded as externally obtained, because the operator
        posting it is asserting that it came from their bot. The report names
        the adapter so a reader can weigh that claim; nothing here can verify
        it, and nothing pretends to.

        Raises:
            NotFoundError: no such run.
            RunNotActiveError: the run has already finished.
            PipelineConfigurationError: the run is not waiting for audio.
        """
        run, meta = self._load_active(run_id)
        awaiting = meta.get("awaiting_bot_audio_for_turn")
        if awaiting is None:
            raise PipelineConfigurationError(
                f"run {run_id} is not waiting for bot audio. Start it first, or "
                "use a run whose bot adapter is 'manual'.",
                run_id=str(run_id),
                stage="bot_exchange",
            )

        events: list[dict[str, Any]] = list(meta.get("events", []))
        artefacts: list[dict[str, Any]] = list(meta.get("artefacts", []))

        reply = BotReply(
            audio=audio,
            content_type=content_type,
            received_from_bot=True,
            metadata={"source": "api_submission"},
        )
        # Validated here, and the failure *raises* rather than failing the
        # run. A malformed upload is the operator's mistake, not a finding
        # about the bot and not a reason to discard a conversation: the run
        # stays where it was, still awaiting audio, so they can post the right
        # file. The HTTP layer turns these into 413/415/422.
        #
        # This is deliberately not `_validate_bot_audio`, which ends the run -
        # correct when a *bot adapter* returned rubbish mid-run, wrong when a
        # person mistyped a filename.
        measured = audio_tools.validate(
            audio,
            accepted=_ACCEPTED_BOT_AUDIO,
            max_bytes=MAX_BOT_AUDIO_BYTES,
        )

        events.append(
            StageEvent(
                turn_index=int(awaiting),
                stage="bot_exchange",
                status="ok",
                detail=f"audio supplied through the API for turn {awaiting}",
            ).as_dict()
        )
        meta["events"] = events
        repo.update_pipeline_metadata(self._session, run, meta)

        ingested = await self._transcribe_reply(
            run_id=run_id,
            reply=reply,
            measured=measured,
            events=events,
            artefacts=artefacts,
        )
        if ingested:
            # Carry on until the next thing that needs input, or the end.
            await self.run_to_completion(run_id)
        return self.report(run_id)

    # -- Closing ------------------------------------------------------------

    def _close_from_caller(
        self,
        run: TestRun,
        meta: dict[str, Any],
        conversation: CallSession,
        events: list[dict[str, Any]],
        artefacts: list[dict[str, Any]],
        transitions: list[dict[str, Any]],
    ) -> None:
        """Finish a run because the conversation reached a terminal state."""
        caller_meta = caller_repo.caller_metadata_of(conversation)
        state = CallerState(caller_meta.get("state", CallerState.INITIAL.value))
        reason = caller_meta.get("termination_reason")
        meta["events"] = events
        meta["artefacts"] = artefacts
        meta["state_transitions"] = transitions

        outcome = _outcome_for(reason, goal_achieved=bool(caller_meta.get("goal_achieved")))
        status = (
            PipelineStatus.COMPLETED
            if state is not CallerState.TERMINATED
            else PipelineStatus.CANCELLED
        )
        self._finish(run, meta, status=status, outcome=outcome)

    def _finish(
        self,
        run: TestRun,
        meta: dict[str, Any],
        *,
        status: PipelineStatus,
        outcome: RunOutcome | None,
        error: str | None = None,
    ) -> None:
        """Record a run's terminal status and outcome."""
        meta["status"] = status.value
        meta["outcome"] = None if outcome is None else outcome.value
        repo.finish_run(
            self._session,
            run,
            status=to_run_status(status),
            metadata=meta,
            error_message=error,
        )
        logger.info(
            "pipeline.run_finished",
            extra={
                "run_id": str(run.id),
                "status": status.value,
                "outcome": None if outcome is None else outcome.value,
                "mode": meta.get("mode"),
            },
        )

    def cancel(self, run_id: uuid.UUID) -> TestRun:
        """Stop a run from outside.

        Records `CANCELLED`, not `FAILED`: an operator stopping a run is not a
        finding about the bot, and a bench that scored it as one would punish
        the bot for the operator's decision.
        """
        run, meta = self._load_active(run_id)
        conversation = repo.conversation_of(self._session, run_id)
        if conversation is not None:
            caller_state = CallerState(
                caller_repo.caller_metadata_of(conversation).get("state", CallerState.INITIAL.value)
            )
            if not caller_state_is_terminal(caller_state):
                self._orchestrator.terminate(conversation.id, reason=TerminationReason.CANCELLED)
        self._finish(run, meta, status=PipelineStatus.CANCELLED, outcome=RunOutcome.CANCELLED)
        return run

    # -- Reporting ----------------------------------------------------------

    def report(self, run_id: uuid.UUID) -> RunReport:
        """Assemble the run's evidence."""
        run, meta = self._load(run_id)
        conversation = repo.conversation_of(self._session, run_id)

        caller_meta = (
            caller_repo.caller_metadata_of(conversation) if conversation is not None else {}
        )
        turns = (
            caller_repo.list_turns(self._session, conversation.id)
            if conversation is not None
            else []
        )
        caller_turns = sum(1 for t in turns if t.speaker.value == Speaker.CALLER.value)
        bot_turns = sum(1 for t in turns if t.speaker.value == Speaker.BOT.value)

        reason = caller_meta.get("termination_reason")
        outcome_value = meta.get("outcome")

        return RunReport(
            run_id=run.id,
            conversation_id=None if conversation is None else conversation.id,
            scenario_name=str(meta.get("scenario_name", "")),
            language=str(meta.get("language", "")),
            mode=ExecutionMode(meta.get("mode", ExecutionMode.OFFLINE_SIMULATION.value)),
            status=PipelineStatus(meta.get("status", PipelineStatus.CREATED.value)),
            outcome=None if outcome_value is None else RunOutcome(outcome_value),
            caller_provider=str(caller_meta.get("provider") or meta.get("caller_provider") or ""),
            uses_language_model=bool(caller_meta.get("uses_language_model", False)),
            stt_provider=meta.get("stt_provider"),
            tts_provider=meta.get("tts_provider"),
            bot_adapter=str(meta.get("bot_adapter", "")),
            bot_audio_externally_received=bool(meta.get("bot_audio_externally_received", False)),
            noise_profile=NoiseProfile(meta.get("noise_profile", NoiseProfile.CLEAN.value)),
            scenario_noise_profile=meta.get("scenario_noise_profile"),
            degradation_seed=meta.get("degradation_seed"),
            awaiting_bot_audio_for_turn=meta.get("awaiting_bot_audio_for_turn"),
            caller_turns=caller_turns,
            bot_turns=bot_turns,
            bot_transcripts_succeeded=int(meta.get("bot_transcripts_succeeded", 0)),
            bot_transcripts_failed=int(meta.get("bot_transcripts_failed", 0)),
            turn_budget=int(meta.get("turn_budget", 0)),
            caller_state=CallerState(caller_meta.get("state", CallerState.INITIAL.value)),
            termination_reason=TerminationReason(reason) if reason else None,
            goal_achieved=bool(caller_meta.get("goal_achieved", False)),
            state_transitions=tuple(meta.get("state_transitions", [])),
            artefacts=tuple(
                ArtefactRecord(
                    turn_index=int(record.get("turn_index", 0)),
                    speaker=str(record.get("speaker", "")),
                    variant=record.get("variant"),
                    reference=str(record.get("reference", "")),
                    size_bytes=int(record.get("size_bytes", 0)),
                    content_type=str(record.get("content_type", "")),
                    sample_rate_hz=record.get("sample_rate_hz"),
                    channels=record.get("channels"),
                    duration_seconds=record.get("duration_seconds"),
                    derived_from=record.get("derived_from"),
                    transformations=tuple(record.get("transformations", [])),
                    degradation_parameters=dict(record.get("degradation_parameters", {})),
                    seed=record.get("seed"),
                )
                for record in meta.get("artefacts", [])
            ),
            events=tuple(
                StageEvent(
                    turn_index=int(event.get("turn_index", 0)),
                    stage=str(event.get("stage", "")),
                    status=str(event.get("status", "")),
                    duration_ms=event.get("duration_ms"),
                    detail=event.get("detail"),
                )
                for event in meta.get("events", [])
            ),
            started_at=None if run.started_at is None else run.started_at.isoformat(),
            finished_at=None if run.finished_at is None else run.finished_at.isoformat(),
            error=run.error_message,
        )

    async def close(self) -> None:
        """Release the bot adapter."""
        await self._bot.close()


def _elapsed(started: float) -> float:
    """Milliseconds since `started`, rounded."""
    return round((monotonic_seconds() - started) * 1000, 3)


def _turn_at(conversation: CallSession, index: int):  # noqa: ANN202 - ORM row
    """The loaded turn at `index`, or None."""
    return next((t for t in conversation.turns if t.turn_index == index), None)


def _outcome_for(reason: str | None, *, goal_achieved: bool) -> RunOutcome:
    """Map the caller's termination reason onto a run outcome.

    One function rather than a scattering of comparisons, because the mapping
    is the thing that decides whether a bot gets blamed: `PROVIDER_ERROR` must
    never arrive here from a caller reason, and a reason this does not
    recognise falls to `NO_PROGRESS` rather than to a success.
    """
    if goal_achieved:
        return RunOutcome.GOAL_ACHIEVED
    mapping = {
        TerminationReason.GOAL_ACHIEVED.value: RunOutcome.GOAL_ACHIEVED,
        TerminationReason.BOT_REFUSED.value: RunOutcome.BOT_REFUSED,
        TerminationReason.BOT_UNINTELLIGIBLE.value: RunOutcome.BOT_UNINTELLIGIBLE,
        TerminationReason.NO_PROGRESS.value: RunOutcome.NO_PROGRESS,
        TerminationReason.TURN_BUDGET_EXHAUSTED.value: RunOutcome.TURN_BUDGET_EXHAUSTED,
        TerminationReason.PROVIDER_ERROR.value: RunOutcome.PROVIDER_ERROR,
        TerminationReason.OPERATOR_TERMINATED.value: RunOutcome.CANCELLED,
        TerminationReason.CANCELLED.value: RunOutcome.CANCELLED,
    }
    return mapping.get(reason or "", RunOutcome.NO_PROGRESS)


__all__ = [
    "MAX_BOT_AUDIO_BYTES",
    "ArtefactRecord",
    "RunConfig",
    "RunEngine",
    "RunReport",
    "StageEvent",
]
