"""Multi-turn conversations, end to end, against real PostgreSQL.

§17 makes a complete offline simulation an acceptance requirement, and this is
it: a whole conversation driven by a scripted bot, with the caller's real rules,
the real state machine and the real tables. No provider, no credential, no
telephony.

These use the `db_session` fixture, so they need a running PostgreSQL
(`docker compose up -d db`) and are never allowed to skip silently.
"""

from __future__ import annotations

import asyncio
import itertools
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest
from sqlalchemy.orm import Session

from app.caller.artefacts import AudioArtefactStore
from app.caller.errors import (
    ConversationNotActiveError,
    ScenarioNotUsableError,
)
from app.caller.orchestrator import ConversationOrchestrator, ConversationReport
from app.caller.providers.deterministic import DeterministicCallerProvider
from app.caller.schemas import TerminationReason
from app.caller.service import CallerService
from app.caller.state import CallerState
from app.core.config import AppEnv, Settings
from app.models import CallSession, CallStatus, Scenario, Speaker
from app.models import TestSuite as SuiteModel
from app.repositories import caller_conversations as repo
from app.services.errors import NotFoundError
from app.transcription.errors import ProviderUnavailableError
from app.transcription.models import TranscriptionResult
from app.transcription.providers.fake import FakeScript, FakeTranscriptionProvider

CLAIM = "0471883"

TAMIL_SPEC: dict[str, Any] = {
    "name": "tamil_crop_insurance_status",
    "description": "A farmer checks a crop insurance claim.",
    "language": "ta-IN",
    "persona": {
        "identity": "Smallholder farmer",
        "speaking_style": "confused",
        "traits": ["unfamiliar with insurance terminology"],
    },
    "goal": {"objective": "Find out the status of my crop insurance claim.", "max_turns": 12},
    "known_facts": {"claim_reference": CLAIM},
    "expected_outcomes": ["Bot states the claim status"],
    "audio": {"noise_profile": "clean", "snr_db": 30.0, "packet_loss_percent": 0.0},
    "constraints": None,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": AppEnv.TEST,
        "secret_key": "test-secret-key-not-used-for-anything",
        "caller_audio_storage_dir": str(tmp_path / "caller-audio"),
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def caller_settings(tmp_path: Path) -> Settings:
    return _settings(tmp_path)


def _make_scenario(
    session: Session, *, language: str = "ta-IN", spec: dict[str, Any] | None = None
) -> tuple[SuiteModel, Scenario]:
    """A suite and one scenario, persisted."""
    suite = SuiteModel(name=f"caller-suite-{uuid.uuid4().hex[:8]}", description="caller fixture")
    session.add(suite)
    session.flush()

    document = dict(spec or TAMIL_SPEC)
    document["language"] = language
    scenario = Scenario(
        suite_id=suite.id,
        name=document["name"],
        description=document.get("description"),
        language=language,
        spec=document,
        spec_version=1,
    )
    session.add(scenario)
    session.flush()
    return suite, scenario


def _orchestrator(
    session: Session,
    settings: Settings,
    *,
    transcription: Any = None,
    artefacts: AudioArtefactStore | None = None,
) -> ConversationOrchestrator:
    caller = CallerService(
        DeterministicCallerProvider(max_clarifications=settings.caller_max_clarifications),
        settings=settings,
    )
    return ConversationOrchestrator(
        session=session,
        caller=caller,
        settings=settings,
        transcription=transcription,
        artefacts=artefacts,
    )


@pytest.fixture
def orchestrator(
    db_session: Session, caller_settings: Settings
) -> Iterator[ConversationOrchestrator]:
    yield _orchestrator(db_session, caller_settings)


@pytest.fixture
def scenario_ids(db_session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    suite, scenario = _make_scenario(db_session)
    return suite.id, scenario.id


def _simulate(
    orchestrator: ConversationOrchestrator,
    scenario_ids: tuple[uuid.UUID, uuid.UUID],
    replies: list[str],
) -> ConversationReport:
    suite_id, scenario_id = scenario_ids
    return asyncio.run(
        orchestrator.simulate(suite_id=suite_id, scenario_id=scenario_id, bot_replies=replies)
    )


# ---------------------------------------------------------------------------
# The mandatory offline simulation
# ---------------------------------------------------------------------------


class TestSuccessfulConversation:
    """A cooperative bot: the caller should get what it came for."""

    REPLIES: ClassVar[list[str]] = [
        "Welcome to the crop insurance helpline.",
        "May I have your claim reference number, please?",
        f"Thank you. Claim {CLAIM} has been approved and payment is scheduled.",
        "Yes, that is correct.",
    ]

    @pytest.fixture
    def report(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
    ) -> ConversationReport:
        return _simulate(orchestrator, scenario_ids, self.REPLIES)

    def test_the_conversation_succeeds(self, report: ConversationReport) -> None:
        assert report.state is CallerState.GOAL_ACHIEVED
        assert report.outcome == "success"
        assert report.goal_achieved
        assert report.termination_reason is TerminationReason.GOAL_ACHIEVED

    def test_it_took_several_turns(self, report: ConversationReport) -> None:
        """A one-turn 'conversation' would prove nothing about multi-turn
        handling, which is what this phase is for."""
        assert report.turns_used >= 4

    def test_it_stayed_inside_the_budget(self, report: ConversationReport) -> None:
        assert report.turns_used <= report.turn_budget
        assert report.turn_budget == 12

    def test_the_caller_supplied_the_claim_reference(
        self,
        report: ConversationReport,
        db_session: Session,
    ) -> None:
        caller_text = " ".join(
            turn.content or ""
            for turn in repo.list_turns(db_session, report.conversation_id)
            if turn.speaker is Speaker.CALLER
        )
        assert CLAIM in caller_text

    def test_several_distinct_rules_fired(self, report: ConversationReport) -> None:
        """Evidence that the caller reacted to the replies rather than walking
        a fixed script."""
        assert len(set(report.rule_ids_fired)) >= 4

    def test_the_report_denies_using_a_language_model(self, report: ConversationReport) -> None:
        assert report.uses_language_model is False
        assert report.provider == "deterministic"

    def test_the_expected_outcome_is_reported_as_observed(self, report: ConversationReport) -> None:
        assert report.outcomes_expected == ("Bot states the claim status",)

    def test_the_conversation_row_is_marked_completed(
        self, report: ConversationReport, db_session: Session
    ) -> None:
        conversation = repo.get_conversation(db_session, report.conversation_id)
        assert conversation is not None
        assert conversation.status is CallStatus.COMPLETED
        assert conversation.ended_at is not None
        assert conversation.error_message is None


class TestFailingConversations:
    """The outcomes must be distinguishable, because they mean different
    things about the bot under test."""

    def test_a_refusing_bot_is_recorded_as_a_refusal(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        report = _simulate(
            orchestrator,
            scenario_ids,
            [
                "I am sorry, I cannot help with claim enquiries.",
                "No, I have no information about that.",
            ],
        )
        assert report.termination_reason is TerminationReason.BOT_REFUSED
        assert report.outcome == "failure"
        assert not report.goal_achieved

    def test_a_silent_bot_is_recorded_as_unintelligible(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        report = _simulate(orchestrator, scenario_ids, ["", "   ", ""])
        assert report.termination_reason is TerminationReason.BOT_UNINTELLIGIBLE
        assert report.outcome == "failure"

    def test_an_evasive_bot_is_recorded_as_no_progress(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        report = _simulate(
            orchestrator,
            scenario_ids,
            ["Our office is in Chennai.", "The weather is fine.", "Have a nice day."],
        )
        assert report.termination_reason is TerminationReason.NO_PROGRESS
        assert report.outcome == "failure"

    def test_a_stalling_bot_exhausts_the_turn_budget(
        self,
        db_session: Session,
        caller_settings: Settings,
    ) -> None:
        """The hard bound. A bot that keeps asking questions forever must not
        produce an endless conversation."""
        spec = {**TAMIL_SPEC, "goal": {**TAMIL_SPEC["goal"], "max_turns": 4}}
        suite, scenario = _make_scenario(db_session, spec=spec)
        orchestrator = _orchestrator(db_session, caller_settings)

        report = asyncio.run(
            orchestrator.simulate(
                suite_id=suite.id,
                scenario_id=scenario.id,
                bot_replies=["And your name?"] * 20,
            )
        )
        assert report.turn_budget == 4
        assert report.turns_used <= 4
        assert report.outcome == "failure"

    def test_the_failure_reasons_are_actually_different(
        self,
        db_session: Session,
        caller_settings: Settings,
    ) -> None:
        """Collapsing them would make the benchmark unable to say *why* a bot
        failed, which is the only useful part of a failure."""
        scripts = {
            "refused": ["I cannot help you.", "I have no record of that."],
            "silent": ["", "", ""],
            "evasive": ["Chennai.", "Fine weather.", "Goodbye."],
        }
        reasons = {}
        for label, replies in scripts.items():
            suite, scenario = _make_scenario(db_session)
            orchestrator = _orchestrator(db_session, caller_settings)
            report = asyncio.run(
                orchestrator.simulate(
                    suite_id=suite.id, scenario_id=scenario.id, bot_replies=replies
                )
            )
            reasons[label] = report.termination_reason
        assert len(set(reasons.values())) == 3, reasons

    def test_a_conversation_row_is_marked_failed(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        db_session: Session,
    ) -> None:
        report = _simulate(orchestrator, scenario_ids, ["I cannot help.", "No record."])
        conversation = repo.get_conversation(db_session, report.conversation_id)
        assert conversation is not None
        assert conversation.status is CallStatus.FAILED


class TestDeterminism:
    def test_the_same_script_produces_the_same_conversation(
        self,
        db_session: Session,
        caller_settings: Settings,
    ) -> None:
        """`is_deterministic` asserted at the level that matters: a whole
        conversation, not one decision. Without this a benchmark run is not
        reproducible."""
        replies = [
            "Welcome to the helpline.",
            "Your claim number, please?",
            f"Claim {CLAIM} is approved.",
            "Yes, that is correct.",
        ]
        transcripts = []
        for _ in range(2):
            suite, scenario = _make_scenario(db_session)
            orchestrator = _orchestrator(db_session, caller_settings)
            report = asyncio.run(
                orchestrator.simulate(
                    suite_id=suite.id, scenario_id=scenario.id, bot_replies=replies
                )
            )
            transcripts.append(
                [
                    (turn.speaker, turn.content)
                    for turn in repo.list_turns(db_session, report.conversation_id)
                ]
            )
        assert transcripts[0] == transcripts[1]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_turns_are_stored_in_order_without_gaps(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        db_session: Session,
    ) -> None:
        report = _simulate(
            orchestrator, scenario_ids, ["Your claim number?", f"Claim {CLAIM} is approved."]
        )
        turns = repo.list_turns(db_session, report.conversation_id)
        assert [turn.turn_index for turn in turns] == list(range(len(turns)))

    def test_speakers_alternate(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        db_session: Session,
    ) -> None:
        report = _simulate(
            orchestrator, scenario_ids, ["Your claim number?", f"Claim {CLAIM} is approved."]
        )
        speakers = [turn.speaker for turn in repo.list_turns(db_session, report.conversation_id)]
        assert speakers[0] is Speaker.CALLER
        for earlier, later in itertools.pairwise(speakers):
            assert earlier is not later

    def test_a_caller_turn_records_its_decision(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        db_session: Session,
    ) -> None:
        """So a run report can say which rule produced which utterance."""
        report = _simulate(orchestrator, scenario_ids, ["Your claim number?"])
        first = repo.list_turns(db_session, report.conversation_id)[0]
        metadata = first.turn_metadata or {}
        assert metadata["intent"] == "open"
        assert metadata["rule_ids"] == ["open.introduce"]
        assert metadata["state_before"] == "initial"
        assert metadata["state_after"] == "introducing"
        assert metadata["explanation"]

    def test_the_facts_a_turn_used_are_recorded(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        db_session: Session,
    ) -> None:
        report = _simulate(orchestrator, scenario_ids, ["Your claim number, please?"])
        used = [
            (turn.turn_metadata or {}).get("facts_used")
            for turn in repo.list_turns(db_session, report.conversation_id)
        ]
        assert ["claim_reference"] in used

    def test_the_caller_metadata_is_namespaced(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        db_session: Session,
    ) -> None:
        """Phase 9 will put telephony metadata in the same column; a namespace
        is what stops the two overwriting each other."""
        report = _simulate(orchestrator, scenario_ids, ["Your claim number?"])
        conversation = repo.get_conversation(db_session, report.conversation_id)
        assert conversation is not None
        assert repo.CALLER_NAMESPACE in (conversation.call_metadata or {})

    def test_metadata_updates_survive_a_reload(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        db_session: Session,
    ) -> None:
        """The JSONB-mutation trap: an in-place edit is silently dropped at
        flush, so a conversation would appear stuck in `initial`."""
        suite_id, scenario_id = scenario_ids
        conversation = orchestrator.start(suite_id=suite_id, scenario_id=scenario_id)
        asyncio.run(orchestrator.next_caller_turn(conversation.id))
        db_session.expire_all()

        reloaded = repo.get_conversation(db_session, conversation.id)
        assert reloaded is not None
        assert repo.caller_metadata_of(reloaded)["state"] == CallerState.INTRODUCING.value

    def test_a_conversation_belongs_to_a_run_and_a_scenario(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        db_session: Session,
    ) -> None:
        """No new tables: Phase 2's foreign keys still hold."""
        _, scenario_id = scenario_ids
        report = _simulate(orchestrator, scenario_ids, ["Your claim number?"])
        conversation = db_session.get(CallSession, report.conversation_id)
        assert conversation is not None
        assert conversation.scenario_id == scenario_id
        assert conversation.test_run_id is not None

    def test_no_phase_six_table_was_added(self, db_session: Session) -> None:
        """Phase 6 reuses the foundational schema, so there is no migration and
        nothing about Phases 1-5 moves."""
        from sqlalchemy import inspect

        tables = set(inspect(db_session.get_bind()).get_table_names())
        assert tables == {
            "alembic_version",
            "call_sessions",
            "conversation_turns",
            "scenarios",
            "test_runs",
            "test_suites",
        }


# ---------------------------------------------------------------------------
# Lifecycle errors
# ---------------------------------------------------------------------------


class TestLifecycleErrors:
    def test_an_unknown_scenario_is_not_found(self, orchestrator: ConversationOrchestrator) -> None:
        with pytest.raises(NotFoundError):
            orchestrator.start(suite_id=uuid.uuid4(), scenario_id=uuid.uuid4())

    def test_an_unsupported_language_is_refused_rather_than_answered_in_english(
        self, db_session: Session, caller_settings: Settings
    ) -> None:
        """A Kannada scenario answered in English would look like a language
        test that passed."""
        suite, scenario = _make_scenario(db_session, language="kn-IN")
        orchestrator = _orchestrator(db_session, caller_settings)
        with pytest.raises(ScenarioNotUsableError) as caught:
            orchestrator.start(suite_id=suite.id, scenario_id=scenario.id)
        assert "kn-IN" in str(caught.value)

    def test_a_finished_conversation_accepts_no_further_turns(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        report = _simulate(orchestrator, scenario_ids, ["I cannot help.", "No record."])
        with pytest.raises(ConversationNotActiveError):
            asyncio.run(orchestrator.next_caller_turn(report.conversation_id))

    def test_a_finished_conversation_accepts_no_bot_text(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        report = _simulate(orchestrator, scenario_ids, ["I cannot help.", "No record."])
        with pytest.raises(ConversationNotActiveError):
            orchestrator.submit_bot_text(report.conversation_id, "hello?")

    def test_reporting_an_unknown_conversation_is_not_found(
        self, orchestrator: ConversationOrchestrator
    ) -> None:
        with pytest.raises(NotFoundError):
            orchestrator.report(uuid.uuid4())

    def test_an_operator_can_terminate_mid_conversation(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        suite_id, scenario_id = scenario_ids
        conversation = orchestrator.start(suite_id=suite_id, scenario_id=scenario_id)
        asyncio.run(orchestrator.next_caller_turn(conversation.id))
        orchestrator.terminate(conversation.id)

        report = orchestrator.report(conversation.id)
        assert report.state is CallerState.TERMINATED
        assert report.outcome == "aborted"
        assert report.termination_reason is TerminationReason.OPERATOR_TERMINATED

    def test_an_aborted_conversation_is_not_a_failure(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        """Cancelling a run must not be scored as a bot defect."""
        suite_id, scenario_id = scenario_ids
        conversation = orchestrator.start(suite_id=suite_id, scenario_id=scenario_id)
        asyncio.run(orchestrator.next_caller_turn(conversation.id))
        orchestrator.terminate(conversation.id, reason=TerminationReason.CANCELLED)
        assert orchestrator.report(conversation.id).outcome == "aborted"

    def test_terminating_twice_is_refused(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        suite_id, scenario_id = scenario_ids
        conversation = orchestrator.start(suite_id=suite_id, scenario_id=scenario_id)
        orchestrator.terminate(conversation.id)
        with pytest.raises(ConversationNotActiveError):
            orchestrator.terminate(conversation.id)

    def test_a_conversation_in_progress_reports_in_progress(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        """Not `failure`. An unfinished run has no outcome yet, and reporting
        one would be a fabricated result."""
        suite_id, scenario_id = scenario_ids
        conversation = orchestrator.start(suite_id=suite_id, scenario_id=scenario_id)
        asyncio.run(orchestrator.next_caller_turn(conversation.id))
        report = orchestrator.report(conversation.id)
        assert report.outcome == "in_progress"
        assert report.termination_reason is None


# ---------------------------------------------------------------------------
# Transcription of bot audio
# ---------------------------------------------------------------------------


class _FailingTranscription:
    """A transcription service whose provider is down."""

    async def transcribe_batch(self, *_: object, **__: object) -> TranscriptionResult:
        raise ProviderUnavailableError("provider unavailable", provider="fake")


class _FixedTranscription:
    """A transcription service that always returns the same text."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def transcribe_batch(self, *_: object, **__: object) -> TranscriptionResult:
        return TranscriptionResult(
            text=self._text,
            language="ta-IN",
            requested_language="ta-IN",
            provider="fake",
            model="fake-1",
            is_final=True,
            latency_ms=1.0,
        )


class TestBotAudio:
    def test_a_transcribed_reply_drives_the_next_turn(
        self,
        db_session: Session,
        caller_settings: Settings,
        wav_16k: bytes,
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        orchestrator = _orchestrator(
            db_session,
            caller_settings,
            transcription=_FixedTranscription("What is your claim number?"),
        )
        conversation = orchestrator.start(suite_id=suite.id, scenario_id=scenario.id)
        asyncio.run(orchestrator.next_caller_turn(conversation.id))
        asyncio.run(orchestrator.submit_bot_audio(conversation.id, audio=wav_16k))
        asyncio.run(orchestrator.next_caller_turn(conversation.id))

        turns = repo.list_turns(db_session, conversation.id)
        assert turns[1].content == "What is your claim number?"
        assert CLAIM in (turns[2].content or "")

    def test_a_transcription_failure_is_a_null_turn_not_an_empty_one(
        self,
        db_session: Session,
        caller_settings: Settings,
        wav_16k: bytes,
    ) -> None:
        """ "The bot was silent" is a bot defect; "we could not transcribe the
        bot" is ours. A pipeline that collapsed them would blame the bot for
        its own deafness."""
        suite, scenario = _make_scenario(db_session)
        orchestrator = _orchestrator(
            db_session, caller_settings, transcription=_FailingTranscription()
        )
        conversation = orchestrator.start(suite_id=suite.id, scenario_id=scenario.id)
        asyncio.run(orchestrator.next_caller_turn(conversation.id))
        asyncio.run(orchestrator.submit_bot_audio(conversation.id, audio=wav_16k))

        bot_turn = repo.list_turns(db_session, conversation.id)[1]
        assert bot_turn.content is None
        assert "ProviderUnavailableError" in (bot_turn.turn_metadata or {})["transcription_error"]

    def test_a_recorded_transcription_error_carries_no_credential(
        self,
        db_session: Session,
        caller_settings: Settings,
        wav_16k: bytes,
    ) -> None:
        """The error text is persisted in `turn_metadata` and returned by the
        API, and provider error strings have carried an Authorization header
        before now."""

        class _LeakyTranscription:
            async def transcribe_batch(self, *_: object, **__: object) -> TranscriptionResult:
                raise ProviderUnavailableError(
                    "upstream rejected Authorization: Bearer sk-live-abcdef123456",
                    provider="fake",
                )

        suite, scenario = _make_scenario(db_session)
        orchestrator = _orchestrator(
            db_session, caller_settings, transcription=_LeakyTranscription()
        )
        conversation = orchestrator.start(suite_id=suite.id, scenario_id=scenario.id)
        asyncio.run(orchestrator.next_caller_turn(conversation.id))
        asyncio.run(orchestrator.submit_bot_audio(conversation.id, audio=wav_16k))

        recorded = (repo.list_turns(db_session, conversation.id)[1].turn_metadata or {})[
            "transcription_error"
        ]
        assert "sk-live-abcdef123456" not in recorded
        assert "ProviderUnavailableError" in recorded

    def test_a_transcription_failure_does_not_end_the_conversation(
        self,
        db_session: Session,
        caller_settings: Settings,
        wav_16k: bytes,
    ) -> None:
        """The caller should ask the bot to repeat, which is what a person
        would do."""
        suite, scenario = _make_scenario(db_session)
        orchestrator = _orchestrator(
            db_session, caller_settings, transcription=_FailingTranscription()
        )
        conversation = orchestrator.start(suite_id=suite.id, scenario_id=scenario.id)
        asyncio.run(orchestrator.next_caller_turn(conversation.id))
        asyncio.run(orchestrator.submit_bot_audio(conversation.id, audio=wav_16k))
        asyncio.run(orchestrator.next_caller_turn(conversation.id))

        assert orchestrator.report(conversation.id).outcome == "in_progress"

    def test_bot_audio_without_a_transcription_service_is_refused(
        self,
        orchestrator: ConversationOrchestrator,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav_16k: bytes,
    ) -> None:
        """Rather than recording an empty transcript, which would look like a
        silent bot."""
        suite_id, scenario_id = scenario_ids
        conversation = orchestrator.start(suite_id=suite_id, scenario_id=scenario_id)
        asyncio.run(orchestrator.next_caller_turn(conversation.id))
        with pytest.raises(ScenarioNotUsableError, match="no transcription service"):
            asyncio.run(orchestrator.submit_bot_audio(conversation.id, audio=wav_16k))

    def test_the_real_fake_provider_also_drives_a_turn(
        self,
        db_session: Session,
        caller_settings: Settings,
        wav_16k: bytes,
    ) -> None:
        """Through the actual `TranscriptionService`, not a stub of it, so the
        wiring between the two subsystems is exercised."""
        from app.services.transcription_service import TranscriptionService

        suite, scenario = _make_scenario(db_session)
        service = TranscriptionService(
            FakeTranscriptionProvider(FakeScript(transcript="Your claim number, please?")),
            settings=caller_settings,
        )
        orchestrator = _orchestrator(db_session, caller_settings, transcription=service)
        conversation = orchestrator.start(suite_id=suite.id, scenario_id=scenario.id)
        asyncio.run(orchestrator.next_caller_turn(conversation.id))
        asyncio.run(orchestrator.submit_bot_audio(conversation.id, audio=wav_16k))
        asyncio.run(orchestrator.next_caller_turn(conversation.id))

        turns = repo.list_turns(db_session, conversation.id)
        assert turns[1].content == "Your claim number, please?"
        assert CLAIM in (turns[2].content or "")


class TestAudioArtefacts:
    def test_bot_audio_is_stored_under_a_relative_reference(
        self,
        db_session: Session,
        caller_settings: Settings,
        tmp_path: Path,
        wav_16k: bytes,
    ) -> None:
        """Relative, because an absolute filesystem path in a database row is
        both useless after a redeploy and an information leak."""
        suite, scenario = _make_scenario(db_session)
        store = AudioArtefactStore(tmp_path / "artefacts")
        orchestrator = _orchestrator(
            db_session,
            caller_settings,
            transcription=_FixedTranscription("Your claim number?"),
            artefacts=store,
        )
        conversation = orchestrator.start(suite_id=suite.id, scenario_id=scenario.id)
        asyncio.run(orchestrator.next_caller_turn(conversation.id))
        asyncio.run(orchestrator.submit_bot_audio(conversation.id, audio=wav_16k))

        reference = (repo.list_turns(db_session, conversation.id)[1].turn_metadata or {})["audio"][
            "reference"
        ]
        assert not Path(reference).is_absolute()
        assert (tmp_path / "artefacts" / reference).read_bytes() == wav_16k
