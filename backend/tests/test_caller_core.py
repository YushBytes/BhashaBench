"""The state machine, the transcript analyser, the schemas and the registry.

Pure logic, no database and no providers. Async code is driven with
`asyncio.run`, as elsewhere in this suite.
"""

from __future__ import annotations

import asyncio

import pytest

from app.caller.analysis import analyse, digit_sequences, mentions_value, normalise
from app.caller.errors import CallerConfigurationError
from app.caller.protocol import CallerProvider
from app.caller.providers.deterministic import (
    PROVIDER_NAME,
    DeterministicCallerProvider,
)
from app.caller.registry import available_providers, build_provider, describe_providers
from app.caller.schemas import (
    CallerContext,
    CallerDecision,
    CallerIntent,
    CallerPersona,
    ConversationTurnView,
    Speaker,
    TerminationReason,
)
from app.caller.state import (
    ALLOWED,
    TERMINAL,
    CallerState,
    can_transition,
    is_terminal,
    outcome_of,
)
from app.core.config import AppEnv, Settings

TAMIL_CLAIM = "0471883"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": AppEnv.TEST,
        "secret_key": "test-secret-key-not-used-for-anything",
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _persona(language: str = "ta-IN") -> CallerPersona:
    return CallerPersona(
        identity="Smallholder farmer",
        speaking_style="confused",
        traits=("unfamiliar with terminology",),
        language=language,
    )


def _context(**overrides: object) -> CallerContext:
    base: dict[str, object] = {
        "scenario_id": "11111111-1111-1111-1111-111111111111",
        "scenario_name": "tamil_crop_insurance_status",
        "objective": "Find out the status of my crop insurance claim.",
        "persona": _persona(),
        "known_facts": {"claim_reference": TAMIL_CLAIM, "registered_name": "Murugan"},
        "state": CallerState.INITIAL,
        "turn_index": 0,
        "turns_remaining": 10,
    }
    base.update(overrides)
    return CallerContext(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class TestStateMachine:
    def test_every_state_has_a_transition_entry(self) -> None:
        """An omitted state would mean an undecidable transition at runtime."""
        assert set(ALLOWED) == set(CallerState)

    def test_the_three_terminal_states_are_terminal(self) -> None:
        assert {
            CallerState.GOAL_ACHIEVED,
            CallerState.FAILED,
            CallerState.TERMINATED,
        } == TERMINAL
        for state in TERMINAL:
            assert is_terminal(state)
            assert ALLOWED[state] == frozenset()

    def test_no_working_state_is_terminal(self) -> None:
        for state in set(CallerState) - TERMINAL:
            assert not is_terminal(state)

    def test_every_non_terminal_state_can_reach_a_terminal_one(self) -> None:
        """This is what makes a runaway conversation impossible by construction
        rather than only by the turn counter."""
        for state in set(CallerState) - TERMINAL:
            assert ALLOWED[state] & TERMINAL, f"{state} cannot terminate"

    def test_terminal_states_have_no_outgoing_transitions(self) -> None:
        for state in TERMINAL:
            for target in CallerState:
                assert not can_transition(state, target)

    def test_the_opening_transition_is_the_only_one_from_initial(self) -> None:
        assert can_transition(CallerState.INITIAL, CallerState.INTRODUCING)
        assert not can_transition(CallerState.INITIAL, CallerState.CONFIRMING)
        assert not can_transition(CallerState.INITIAL, CallerState.GOAL_ACHIEVED)

    def test_confirming_cannot_slide_back_to_asking(self) -> None:
        """A caller that could would never settle on an answer."""
        assert not can_transition(CallerState.CONFIRMING, CallerState.AWAITING_INFORMATION)
        assert can_transition(CallerState.CONFIRMING, CallerState.GOAL_ACHIEVED)
        assert can_transition(CallerState.CONFIRMING, CallerState.SEEKING_CLARIFICATION)

    @pytest.mark.parametrize(
        "state",
        [
            CallerState.AWAITING_INFORMATION,
            CallerState.PROVIDING_DETAILS,
            CallerState.SEEKING_CLARIFICATION,
        ],
    )
    def test_working_states_may_self_transition(self, state: CallerState) -> None:
        """A caller can ask twice; the turn budget is what stops it, not the
        state machine."""
        assert can_transition(state, state)

    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (CallerState.GOAL_ACHIEVED, "success"),
            (CallerState.FAILED, "failure"),
            (CallerState.TERMINATED, "aborted"),
        ],
    )
    def test_terminal_outcomes_are_distinct(self, state: CallerState, expected: str) -> None:
        """Three outcomes, not one: a provider outage must not look like a bot
        defect."""
        assert outcome_of(state) == expected

    def test_asking_the_outcome_of_a_live_conversation_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="not a terminal state"):
            outcome_of(CallerState.AWAITING_INFORMATION)


# ---------------------------------------------------------------------------
# Decision schema
# ---------------------------------------------------------------------------


class TestDecisionValidation:
    def _decision(self, **overrides: object) -> CallerDecision:
        base: dict[str, object] = {
            "message": "hello",
            "intent": CallerIntent.ASK,
            "next_state": CallerState.AWAITING_INFORMATION,
            "explanation": "because",
        }
        base.update(overrides)
        return CallerDecision(**base)  # type: ignore[arg-type]

    def test_an_empty_message_is_rejected_by_the_schema(self) -> None:
        """An empty utterance must never reach speech synthesis."""
        with pytest.raises(ValueError, match="at least 1 character"):
            self._decision(message="")

    def test_terminating_without_a_reason_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must carry a termination_reason"):
            self._decision(should_terminate=True, next_state=CallerState.FAILED)

    def test_a_reason_without_terminating_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="contradictory"):
            self._decision(termination_reason=TerminationReason.NO_PROGRESS)

    def test_goal_achieved_must_agree_with_the_state(self) -> None:
        with pytest.raises(ValueError, match="must agree"):
            self._decision(goal_achieved=True)

    def test_goal_achieved_state_must_agree_with_the_flag(self) -> None:
        with pytest.raises(ValueError, match="goal_achieved is False"):
            self._decision(
                next_state=CallerState.GOAL_ACHIEVED,
                should_terminate=True,
                termination_reason=TerminationReason.GOAL_ACHIEVED,
            )

    def test_a_coherent_success_decision_is_accepted(self) -> None:
        decision = self._decision(
            next_state=CallerState.GOAL_ACHIEVED,
            goal_achieved=True,
            should_terminate=True,
            termination_reason=TerminationReason.GOAL_ACHIEVED,
        )
        assert decision.goal_achieved


class TestContextProjection:
    def test_expected_outcomes_are_absent_from_the_context(self) -> None:
        """The caller must not be able to read the marking scheme."""
        assert "expected_outcomes" not in CallerContext.model_fields
        assert "outcomes" not in CallerContext.model_fields

    def test_is_opening_only_on_the_very_first_turn(self) -> None:
        assert _context().is_opening
        assert not _context(
            history=(ConversationTurnView(index=0, speaker=Speaker.CALLER, text="hi"),),
            state=CallerState.INTRODUCING,
        ).is_opening

    def test_last_bot_text_is_empty_rather_than_none(self) -> None:
        assert _context().last_bot_text == ""


# ---------------------------------------------------------------------------
# Transcript analysis
# ---------------------------------------------------------------------------


class TestNormalisation:
    def test_case_and_punctuation_are_folded(self) -> None:
        assert normalise("Hello, World!") == "hello world"

    def test_whitespace_is_collapsed(self) -> None:
        assert normalise("a   b\n\tc") == "a b c"

    @pytest.mark.parametrize(
        ("script", "text", "expected"),
        [
            ("Tamil", "௦௪௭௧௮௮௩", "0471883"),
            ("Devanagari", "०४७१८८३", "0471883"),
            ("Bengali", "০৪৭১৮৮৩", "0471883"),
            ("Telugu", "౦౪౭౧౮౮౩", "0471883"),
            ("Gujarati", "૦૪૭૧૮૮૩", "0471883"),
        ],
    )
    def test_indic_digits_become_ascii(self, script: str, text: str, expected: str) -> None:
        """A bot that returns Tamil numerals has still said the number."""
        assert normalise(text) == expected, script

    def test_unicode_is_normalised_before_comparison(self) -> None:
        """A composed and a decomposed form must compare equal."""
        assert normalise("ே") == normalise("ே")
        # The fullwidth characters are the input under test, not a typo: a
        # transcript can arrive in this form, and NFKC is what folds it.
        assert normalise("ｆｕｌｌ０４７") == "full047"  # noqa: RUF001


class TestDigitExtraction:
    @pytest.mark.parametrize(
        "spelling",
        [
            "0471883",
            "047 1883",
            "047-1883",
            "0 4 7 1 8 8 3",
            "zero four seven one eight eight three",
        ],
    )
    def test_a_reference_number_is_found_however_it_is_written(self, spelling: str) -> None:
        """The reason substring matching is not good enough: all five of these
        are the same number to a human."""
        assert mentions_value(f"your claim is {spelling} sir", TAMIL_CLAIM)

    def test_a_different_number_is_not_a_match(self) -> None:
        assert not mentions_value("your claim is 9988776 sir", TAMIL_CLAIM)

    def test_tamil_numerals_match_an_ascii_fact(self) -> None:
        assert mentions_value("உங்கள் எண் ௦௪௭௧௮௮௩", TAMIL_CLAIM)

    def test_digit_sequences_are_deduplicated(self) -> None:
        sequences = digit_sequences("047 1883")
        assert "0471883" in sequences
        assert len(sequences) == len(set(sequences))

    def test_a_name_matches_as_a_whole_word_only(self) -> None:
        """So 'Meena' does not match inside 'Meenakshi'."""
        assert mentions_value("the name is Murugan", "Murugan")
        assert not mentions_value("the name is Muruganandam", "Murugan")

    def test_an_empty_value_never_matches(self) -> None:
        assert not mentions_value("anything at all", "")


class TestSignalExtraction:
    def test_a_none_transcript_is_empty(self) -> None:
        signals = analyse(None, language="ta-IN")
        assert signals.is_empty
        assert not signals.is_usable

    def test_a_whitespace_transcript_is_empty(self) -> None:
        assert analyse("   ", language="ta-IN").is_empty

    def test_an_identifier_request_is_detected_in_english(self) -> None:
        signals = analyse("Could you please provide your claim number?", language="ta-IN")
        assert signals.asks_for_identifier
        assert signals.asks_question

    def test_an_identifier_request_is_detected_in_tamil(self) -> None:
        signals = analyse("உங்கள் கோரிக்கை எண் என்ன?", language="ta-IN")
        assert signals.asks_for_identifier

    def test_english_keywords_are_matched_even_in_a_tamil_scenario(self) -> None:
        """The code-switching this project exists to measure: a Tamil bot
        routinely says 'reference number' in English."""
        signals = analyse("உங்கள் reference number சொல்லுங்க", language="ta-IN")
        assert signals.asks_for_identifier

    def test_a_confirmation_is_detected(self) -> None:
        assert analyse("Your claim has been approved.", language="en-IN").confirms

    def test_a_refusal_is_detected(self) -> None:
        assert analyse("I cannot help with that.", language="en-IN").refuses

    def test_a_refusal_beats_a_confirmation_when_both_appear(self) -> None:
        """'I can confirm we have no record' is a refusal, and scoring it as a
        success would pass a failed call."""
        signals = analyse("I can confirm that we have no record of your claim.", language="en-IN")
        assert signals.refuses
        assert not signals.confirms

    def test_a_repeat_request_is_detected(self) -> None:
        signals = analyse("Sorry, could you repeat that?", language="en-IN")
        assert signals.requests_repeat
        assert not signals.is_usable

    def test_an_echoed_fact_is_reported(self) -> None:
        signals = analyse(
            "I have your claim 0471883 here.",
            language="ta-IN",
            known_facts={"claim_reference": TAMIL_CLAIM},
        )
        assert signals.facts_echoed == ("claim_reference",)
        assert signals.facts_contradicted == ()

    def test_a_contradicted_digit_fact_is_reported(self) -> None:
        """The bot quoted a number where this fact is a number, and got it
        wrong."""
        signals = analyse(
            "Your claim 9988776 is pending.",
            language="ta-IN",
            known_facts={"claim_reference": TAMIL_CLAIM},
        )
        assert signals.facts_contradicted == ("claim_reference",)

    def test_a_free_text_fact_is_never_reported_as_contradicted(self) -> None:
        """A different wording is not a different fact, so nothing is claimed."""
        signals = analyse(
            "The policyholder is someone else.",
            language="en-IN",
            known_facts={"registered_name": "Murugan"},
        )
        assert signals.facts_contradicted == ()

    def test_several_signals_can_hold_at_once(self) -> None:
        signals = analyse(
            "Thank you, that is correct. Now, what is your account number?",
            language="en-IN",
        )
        assert signals.confirms
        assert signals.asks_for_identifier

    def test_ordinary_text_sets_no_signals(self) -> None:
        signals = analyse("The weather is pleasant today.", language="en-IN")
        assert not signals.asks_for_identifier
        assert not signals.confirms
        assert not signals.refuses
        assert not signals.requests_repeat


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_only_the_deterministic_provider_is_registered(self) -> None:
        assert available_providers() == (PROVIDER_NAME,)

    def test_there_is_no_evon_provider(self) -> None:
        """A stub that raised on every call would advertise Evon as a
        configurable option. The honest answer is 'not a known provider'."""
        assert "evon" not in available_providers()
        with pytest.raises(CallerConfigurationError) as caught:
            build_provider(_settings(caller_provider="evon"))
        assert "not a known caller provider" in str(caught.value)

    def test_the_unknown_provider_error_explains_why_evon_is_absent(self) -> None:
        with pytest.raises(CallerConfigurationError) as caught:
            build_provider(_settings(caller_provider="evon"))
        message = str(caught.value)
        assert "no text-generation endpoint is documented" in message
        assert "no hosted inference provider" in message

    def test_the_configured_provider_is_built(self) -> None:
        assert build_provider(_settings()).capabilities.name == PROVIDER_NAME

    @pytest.mark.parametrize("spelling", ["DETERMINISTIC", "  deterministic  "])
    def test_the_provider_name_is_normalised(self, spelling: str) -> None:
        assert build_provider(_settings(caller_provider=spelling)).capabilities.name == (
            PROVIDER_NAME
        )

    def test_the_provider_needs_no_credentials(self) -> None:
        """Which is why the caller works in CI and on a fresh checkout."""
        assert build_provider(_settings()).capabilities.requires_credentials is False

    def test_describe_lists_the_registered_provider(self) -> None:
        described = describe_providers(_settings())
        assert [name for name, _, _ in described] == [PROVIDER_NAME]
        assert described[0][1] is not None
        assert described[0][2] is None


class TestCapabilities:
    def test_the_provider_satisfies_the_protocol(self) -> None:
        assert isinstance(DeterministicCallerProvider(), CallerProvider)

    def test_it_does_not_claim_to_use_a_language_model(self) -> None:
        """The single most important assertion in this module."""
        assert DeterministicCallerProvider().capabilities.uses_language_model is False

    def test_it_declares_itself_deterministic(self) -> None:
        assert DeterministicCallerProvider().capabilities.is_deterministic is True

    def test_it_only_claims_languages_with_reviewed_phrase_tables(self) -> None:
        caps = DeterministicCallerProvider().capabilities
        assert caps.languages == frozenset({"ta-IN", "hi-IN", "en-IN"})

    def test_it_does_not_claim_code_mixing(self) -> None:
        assert DeterministicCallerProvider().capabilities.supports_code_mixing is False

    def test_its_notes_say_it_is_not_a_language_model(self) -> None:
        notes = " ".join(DeterministicCallerProvider().capabilities.notes).lower()
        assert "not a language model" in notes
        assert "evon" in notes

    def test_the_same_context_always_yields_the_same_decision(self) -> None:
        """What `is_deterministic` actually claims, asserted rather than
        trusted."""
        provider = DeterministicCallerProvider()
        context = _context()
        first = asyncio.run(provider.decide(context))
        second = asyncio.run(provider.decide(context))
        assert first == second

    def test_close_is_idempotent(self) -> None:
        provider = DeterministicCallerProvider()
        asyncio.run(provider.close())
        asyncio.run(provider.close())
