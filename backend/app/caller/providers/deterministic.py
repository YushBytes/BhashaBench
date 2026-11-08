"""The deterministic, rule-based caller.

**This is not a language model and is not Gnani Evon.** It is an ordered set of
rules over the signals in `app.caller.analysis`. Phase 6 ships it because Gate
A established that no Gnani text-generation endpoint is documented and no
hosted inference for `gnani/gnani-evon-v3.3-30B-A3B` is advertised. The name
says what it is, `CallerCapabilities.uses_language_model` is `False`, and the
documentation says so in those words.

What it genuinely does: respond differently to different bot utterances. The
same scenario against a bot that asks for a reference number, a bot that
refuses, a bot that mishears and a bot that answers produces four different
conversations. What it cannot do: handle an utterance no rule anticipates with
anything better than a clarification request. That is the honest ceiling of a
rule engine, and it is why the Evon extension point exists.

**Rule order is the design.** Rules are evaluated top to bottom and the first
match wins, so the ordering encodes priority: a refusal is handled before a
question, because a bot that says "I cannot help, what is your number?" has
refused. Each rule has a stable `id` that lands in the database, so a run
report can say which rule drove which turn and a test can assert on it.

Utterance text comes from per-language phrase tables. These are fixed strings,
not generation - a caller in a language with no table falls back to English
rather than emitting a machine-translated approximation nobody has reviewed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.caller.analysis import TranscriptSignals, analyse
from app.caller.protocol import CallerCapabilities
from app.caller.schemas import (
    CallerContext,
    CallerDecision,
    CallerIntent,
    TerminationReason,
)
from app.caller.state import CallerState

PROVIDER_NAME = "deterministic"

# Languages with reviewed phrase tables below. Deliberately narrow: Tamil
# because it is the flagship scenario, Hindi as the largest, English as the
# fallback. A scenario in another catalogue language still runs - it composes
# in English - and `CallerCapabilities.notes` says so rather than implying
# coverage that does not exist.
_REVIEWED_LANGUAGES = frozenset({"ta-IN", "hi-IN", "en-IN"})

# States in which a bare question from the bot is answered with the next unused
# known fact, rather than only an explicitly identifier-shaped request.
#
# A real helpline asks "and your registered name, please?" far more often than
# it says "reference number", and a caller that answered the second but
# clarified at the first would stall on the most ordinary turn in the script.
# Two states are deliberately excluded. In INITIAL/INTRODUCING the caller has
# not yet asked its own question, and volunteering a claim number in reply to
# "how may I help you?" would mask a bot that never asks for one. In CONFIRMING
# the caller is closing, and a fresh fact would reopen a conversation it had
# already finished.
_ANSWERS_BARE_QUESTIONS_IN = frozenset(
    {
        CallerState.AWAITING_INFORMATION,
        CallerState.PROVIDING_DETAILS,
        CallerState.SEEKING_CLARIFICATION,
    }
)


@dataclass(frozen=True, slots=True)
class _Phrases:
    """Fixed utterance templates for one language.

    `{fact}` is the only substitution, and it is always a value from the
    scenario's `known_facts` - which is how §9's "do not invent facts" holds
    structurally rather than by inspection.
    """

    opening: str
    ask: str
    provide_fact: str
    clarify: str
    repeat_request: str
    correct: str
    decline_unknown: str
    confirm: str
    close_success: str
    close_failure: str


_TAMIL = _Phrases(
    opening="வணக்கம், நான் {identity}. {objective}",
    ask="அதைப் பற்றி சொல்ல முடியுமா?",
    provide_fact="ஆமாம், அது {fact}.",
    clarify="மன்னிக்கவும், அது சரியாகப் புரியவில்லை. இன்னும் தெளிவாகச் சொல்ல முடியுமா?",
    repeat_request="மன்னிக்கவும், மறுபடி சொல்லுங்கள்.",
    correct="இல்லை, அது சரியல்ல. சரியான விவரம் {fact}.",
    decline_unknown="மன்னிக்கவும், அது எனக்குத் தெரியாது.",
    confirm="சரி, அது {fact} என்று சொல்கிறீர்கள், சரியா?",
    close_success="நன்றி, எனக்குத் தேவையான தகவல் கிடைத்துவிட்டது.",
    close_failure="சரி, நன்றி. நான் பிறகு முயற்சி செய்கிறேன்.",
)

_HINDI = _Phrases(
    opening="नमस्ते, मैं {identity} हूँ। {objective}",
    ask="क्या आप इसके बारे में बता सकते हैं?",
    provide_fact="जी हाँ, वह {fact} है।",
    clarify="माफ़ कीजिए, मुझे ठीक से समझ नहीं आया। क्या आप और साफ़ बता सकते हैं?",
    repeat_request="माफ़ कीजिए, कृपया फिर से बताइए।",
    correct="नहीं, वह सही नहीं है। सही जानकारी {fact} है।",
    decline_unknown="माफ़ कीजिए, यह मुझे नहीं पता।",
    confirm="ठीक है, आप कह रहे हैं कि वह {fact} है, सही?",
    close_success="धन्यवाद, मुझे ज़रूरी जानकारी मिल गई।",
    close_failure="ठीक है, धन्यवाद। मैं बाद में कोशिश करूँगा।",
)

_ENGLISH = _Phrases(
    opening="Hello, I am {identity}. {objective}",
    ask="Could you tell me about that, please?",
    provide_fact="Yes, it is {fact}.",
    clarify="Sorry, I did not quite follow that. Could you explain it more clearly?",
    repeat_request="Sorry, could you say that again?",
    correct="No, that is not right. The correct detail is {fact}.",
    decline_unknown="Sorry, I do not know that.",
    confirm="Right, so you are saying it is {fact} - is that correct?",
    close_success="Thank you, I have got what I needed.",
    close_failure="All right, thank you. I will try again later.",
)

_TABLES: dict[str, _Phrases] = {"ta-IN": _TAMIL, "hi-IN": _HINDI, "en-IN": _ENGLISH}


def _phrases(language: str) -> _Phrases:
    """The phrase table for `language`, falling back to English.

    A fallback rather than a failure: a scenario in Kannada should still be
    runnable end to end, and an English caller is an honest limitation that the
    capabilities declare. Emitting unreviewed machine-translated Kannada would
    be worse - nobody could tell a bad bot from a bad caller.
    """
    return _TABLES.get(language, _ENGLISH)


@dataclass(frozen=True, slots=True)
class _Rule:
    """One branch of the caller's behaviour."""

    id: str
    describe: str
    matches: Callable[[CallerContext, TranscriptSignals], bool]
    decide: Callable[[CallerContext, TranscriptSignals], CallerDecision]


class DeterministicCallerProvider:
    """A `CallerProvider` driven by rules, not by a model."""

    def __init__(self, *, max_clarifications: int = 2) -> None:
        self._max_clarifications = max_clarifications
        self._rules = self._build_rules()

    @property
    def capabilities(self) -> CallerCapabilities:
        return CallerCapabilities(
            name=PROVIDER_NAME,
            display_name="Deterministic rule-based caller",
            is_deterministic=True,
            # The field that matters most on this provider. False, and the
            # documentation repeats it: this is not Evon and not a model.
            uses_language_model=False,
            languages=_REVIEWED_LANGUAGES,
            supports_code_mixing=False,
            requires_credentials=False,
            max_turns_supported=None,
            notes=(
                "Rule-based, not a language model. Official Gnani Evon "
                "integration is deferred until documented access and "
                "credentials are available.",
                "Utterances come from fixed per-language phrase tables. "
                f"Reviewed tables exist for {sorted(_REVIEWED_LANGUAGES)}; a "
                "scenario in any other catalogue language composes in English "
                "rather than emitting unreviewed translation.",
                "Code-mixing is not generated. A scenario may declare it and "
                "the caller will not produce it, so a code-mixing scenario "
                "exercises the bot's handling of monolingual caller speech "
                "only in this phase.",
                "Concrete details are only ever quoted from the scenario's "
                "known_facts. The caller cannot invent a reference number.",
                "An utterance no rule anticipates produces a clarification "
                "request. That is the ceiling of a rule engine.",
            ),
        )

    # -- Rules --------------------------------------------------------------

    def _build_rules(self) -> tuple[_Rule, ...]:
        """Assemble the rule set. Order is priority; first match wins."""
        return (
            _Rule(
                id="budget.exhausted",
                describe="No turns left: close without the objective met.",
                matches=lambda ctx, _: (
                    ctx.turns_remaining <= 1 and ctx.state is not CallerState.INITIAL
                ),
                decide=self._close_out_of_budget,
            ),
            _Rule(
                id="open.introduce",
                describe="First turn: introduce and state the objective.",
                matches=lambda ctx, _: ctx.is_opening,
                decide=self._open,
            ),
            _Rule(
                id="bot.refused",
                describe="Bot refused or has no information: one clarification, then close.",
                matches=lambda _, sig: sig.refuses,
                decide=self._handle_refusal,
            ),
            _Rule(
                id="bot.silent",
                describe="Nothing transcribed: ask the bot to repeat.",
                matches=lambda _, sig: sig.is_empty,
                decide=self._handle_silence,
            ),
            _Rule(
                id="bot.misheard",
                describe="Bot asked the caller to repeat: say it again.",
                matches=lambda _, sig: sig.requests_repeat,
                decide=self._handle_repeat_request,
            ),
            _Rule(
                id="bot.wrong_fact",
                describe="Bot stated a known fact incorrectly: correct it.",
                matches=lambda _, sig: bool(sig.facts_contradicted),
                decide=self._correct_fact,
            ),
            _Rule(
                id="caller.confirmed_close",
                describe="Caller was confirming and the bot did not object: close successfully.",
                # Position matters, and this is the subtle one. CONFIRMING is a
                # closing state: the only exits the state machine allows are
                # SEEKING_CLARIFICATION and the terminal three. Every rule above
                # targets one of those, and every rule below targets a state
                # CONFIRMING cannot reach - so this has to sit here, above them,
                # or a bot that answers a read-back with "yes, that is correct"
                # drives `confirming -> confirming` and the decision is rejected.
                matches=lambda ctx, sig: ctx.state is CallerState.CONFIRMING and not sig.refuses,
                decide=self._close_success,
            ),
            _Rule(
                id="bot.asked_for_identifier",
                describe="Bot asked for a detail the caller holds: supply it.",
                matches=lambda ctx, sig: (
                    (
                        sig.asks_for_identifier
                        or (
                            sig.asks_question
                            and not sig.confirms
                            and ctx.state in _ANSWERS_BARE_QUESTIONS_IN
                        )
                    )
                    and self._unused_fact(ctx) is not None
                ),
                decide=self._provide_fact,
            ),
            _Rule(
                id="bot.asked_unknown",
                describe="Bot asked for something not in the scenario: say so truthfully.",
                matches=lambda ctx, sig: (
                    (sig.asks_for_identifier or sig.asks_question)
                    and self._unused_fact(ctx) is None
                    and not sig.confirms
                ),
                decide=self._decline_unknown,
            ),
            _Rule(
                id="bot.confirmed",
                describe="Bot confirmed: read it back, then close on the next turn.",
                matches=lambda _, sig: sig.confirms,
                decide=self._confirm,
            ),
            _Rule(
                id="fallback.clarify",
                describe="Nothing matched: press for a usable answer.",
                matches=lambda *_: True,
                decide=self._clarify,
            ),
        )

    # -- Decision helpers ---------------------------------------------------

    def _unused_fact(self, ctx: CallerContext) -> tuple[str, str] | None:
        """The next known fact the caller has not already volunteered.

        Tracked through history rather than on the instance, so the provider
        holds no per-conversation state and the same context always yields the
        same decision - which is what `is_deterministic` claims.
        """
        already: set[str] = set()
        for turn in ctx.history:
            if turn.speaker.value == "caller" and turn.intent in {
                CallerIntent.PROVIDE_FACT,
                CallerIntent.CORRECT,
            }:
                for key, value in ctx.known_facts.items():
                    if value and value in turn.text:
                        already.add(key)
        for key, value in ctx.known_facts.items():
            if key not in already and value:
                return key, value
        return None

    def _clarification_count(self, ctx: CallerContext) -> int:
        """How many times the caller has already asked for clarification."""
        return sum(
            1
            for turn in ctx.history
            if turn.intent in {CallerIntent.CLARIFY, CallerIntent.REPEAT_REQUEST}
        )

    def _open(self, ctx: CallerContext, _: TranscriptSignals) -> CallerDecision:
        phrases = _phrases(ctx.persona.language)
        message = phrases.opening.format(identity=ctx.persona.identity, objective=ctx.objective)
        return CallerDecision(
            message=message,
            intent=CallerIntent.OPEN,
            next_state=CallerState.INTRODUCING,
            explanation="Opening turn: introduced the persona and stated the objective.",
            rule_ids=("open.introduce",),
        )

    def _provide_fact(self, ctx: CallerContext, _: TranscriptSignals) -> CallerDecision:
        found = self._unused_fact(ctx)
        # `matches` already established this, but a rule that reads a value it
        # has not re-checked is how a None slips into an f-string.
        if found is None:  # pragma: no cover - guarded by the rule predicate
            return self._clarify(ctx, _)
        key, value = found
        phrases = _phrases(ctx.persona.language)
        return CallerDecision(
            message=phrases.provide_fact.format(fact=value),
            intent=CallerIntent.PROVIDE_FACT,
            next_state=CallerState.PROVIDING_DETAILS,
            explanation=f"Bot asked for an identifier; supplied known fact '{key}'.",
            rule_ids=("bot.asked_for_identifier",),
            facts_used=(key,),
        )

    def _correct_fact(self, ctx: CallerContext, sig: TranscriptSignals) -> CallerDecision:
        key = sig.facts_contradicted[0]
        value = ctx.known_facts[key]
        phrases = _phrases(ctx.persona.language)
        return CallerDecision(
            message=phrases.correct.format(fact=value),
            intent=CallerIntent.CORRECT,
            next_state=CallerState.SEEKING_CLARIFICATION,
            explanation=f"Bot stated '{key}' incorrectly; corrected it from known facts.",
            rule_ids=("bot.wrong_fact",),
            facts_used=(key,),
        )

    def _decline_unknown(self, ctx: CallerContext, _: TranscriptSignals) -> CallerDecision:
        """Say truthfully that the caller does not know.

        §9's rule, implemented rather than asserted: there is no branch here
        that fabricates a plausible value, so a bot asking for something the
        scenario never supplied gets "I don't know" every time.
        """
        phrases = _phrases(ctx.persona.language)
        return CallerDecision(
            message=phrases.decline_unknown,
            intent=CallerIntent.DECLINE_UNKNOWN,
            next_state=CallerState.AWAITING_INFORMATION,
            explanation="Bot asked for information absent from the scenario; "
            "declined truthfully rather than inventing it.",
            rule_ids=("bot.asked_unknown",),
        )

    def _confirm(self, ctx: CallerContext, sig: TranscriptSignals) -> CallerDecision:
        phrases = _phrases(ctx.persona.language)
        # Read back the fact the bot echoed when there is one, otherwise the
        # bot's own words - never a value the caller made up.
        if sig.facts_echoed:
            key = sig.facts_echoed[0]
            readback = ctx.known_facts[key]
            used = (key,)
        else:
            readback = sig.raw.strip()[:160]
            used = ()
        return CallerDecision(
            message=phrases.confirm.format(fact=readback),
            intent=CallerIntent.CONFIRM,
            next_state=CallerState.CONFIRMING,
            explanation="Bot confirmed; reading the detail back to check it.",
            rule_ids=("bot.confirmed",),
            facts_used=used,
        )

    def _close_success(self, ctx: CallerContext, _: TranscriptSignals) -> CallerDecision:
        phrases = _phrases(ctx.persona.language)
        return CallerDecision(
            message=phrases.close_success,
            intent=CallerIntent.CLOSE,
            next_state=CallerState.GOAL_ACHIEVED,
            goal_achieved=True,
            should_terminate=True,
            termination_reason=TerminationReason.GOAL_ACHIEVED,
            explanation="Read-back accepted; the caller has what it came for.",
            rule_ids=("caller.confirmed_close",),
        )

    def _close_out_of_budget(self, ctx: CallerContext, _: TranscriptSignals) -> CallerDecision:
        phrases = _phrases(ctx.persona.language)
        return CallerDecision(
            message=phrases.close_failure,
            intent=CallerIntent.CLOSE,
            next_state=CallerState.FAILED,
            should_terminate=True,
            termination_reason=TerminationReason.TURN_BUDGET_EXHAUSTED,
            explanation="Turn budget exhausted without meeting the objective.",
            rule_ids=("budget.exhausted",),
        )

    def _handle_refusal(self, ctx: CallerContext, _: TranscriptSignals) -> CallerDecision:
        """Press once, then stop.

        A caller that kept asking a bot which has said "no record found" would
        burn the whole turn budget and report a turn-limit failure, hiding the
        actual finding - that the bot refused.
        """
        phrases = _phrases(ctx.persona.language)
        if self._clarification_count(ctx) >= 1:
            return CallerDecision(
                message=phrases.close_failure,
                intent=CallerIntent.CLOSE,
                next_state=CallerState.FAILED,
                should_terminate=True,
                termination_reason=TerminationReason.BOT_REFUSED,
                explanation="Bot refused again after one clarification; closing.",
                rule_ids=("bot.refused", "refusal.second"),
            )
        return CallerDecision(
            message=phrases.clarify,
            intent=CallerIntent.CLARIFY,
            next_state=CallerState.SEEKING_CLARIFICATION,
            explanation="Bot refused or had no information; pressing once.",
            rule_ids=("bot.refused", "refusal.first"),
        )

    def _handle_silence(self, ctx: CallerContext, _: TranscriptSignals) -> CallerDecision:
        phrases = _phrases(ctx.persona.language)
        if self._clarification_count(ctx) >= self._max_clarifications:
            return CallerDecision(
                message=phrases.close_failure,
                intent=CallerIntent.CLOSE,
                next_state=CallerState.FAILED,
                should_terminate=True,
                termination_reason=TerminationReason.BOT_UNINTELLIGIBLE,
                explanation=(
                    f"Nothing transcribable after {self._max_clarifications} attempts; closing."
                ),
                rule_ids=("bot.silent", "silence.exhausted"),
            )
        return CallerDecision(
            message=phrases.repeat_request,
            intent=CallerIntent.REPEAT_REQUEST,
            next_state=CallerState.SEEKING_CLARIFICATION,
            explanation="Nothing transcribable from the bot; asked it to repeat.",
            rule_ids=("bot.silent",),
        )

    def _handle_repeat_request(self, ctx: CallerContext, _: TranscriptSignals) -> CallerDecision:
        """The bot misheard the caller. Say the same thing again.

        Repeating the caller's own last utterance rather than rephrasing: the
        scenario is testing whether the bot can hear this speech, and changing
        the words would change the test.
        """
        phrases = _phrases(ctx.persona.language)
        previous = next((t for t in reversed(ctx.history) if t.speaker.value == "caller"), None)
        if previous is not None and self._clarification_count(ctx) < self._max_clarifications:
            return CallerDecision(
                message=previous.text,
                intent=CallerIntent.REPEAT_REQUEST,
                next_state=CallerState.SEEKING_CLARIFICATION,
                explanation="Bot asked the caller to repeat; restated the same utterance.",
                rule_ids=("bot.misheard", "misheard.restate"),
            )
        return CallerDecision(
            message=phrases.close_failure,
            intent=CallerIntent.CLOSE,
            next_state=CallerState.FAILED,
            should_terminate=True,
            termination_reason=TerminationReason.NO_PROGRESS,
            explanation="Bot repeatedly could not understand the caller; closing.",
            rule_ids=("bot.misheard", "misheard.exhausted"),
        )

    def _clarify(self, ctx: CallerContext, _: TranscriptSignals) -> CallerDecision:
        phrases = _phrases(ctx.persona.language)
        if self._clarification_count(ctx) >= self._max_clarifications:
            return CallerDecision(
                message=phrases.close_failure,
                intent=CallerIntent.CLOSE,
                next_state=CallerState.FAILED,
                should_terminate=True,
                termination_reason=TerminationReason.NO_PROGRESS,
                explanation=(
                    f"No usable answer after {self._max_clarifications} clarifications; closing."
                ),
                rule_ids=("fallback.clarify", "clarify.exhausted"),
            )
        # The first unmatched utterance is answered by asking the scenario's
        # question, not by clarifying - on turn two the caller has introduced
        # itself and the bot has said something neutral like a greeting.
        if ctx.state is CallerState.INTRODUCING:
            return CallerDecision(
                message=phrases.ask,
                intent=CallerIntent.ASK,
                next_state=CallerState.AWAITING_INFORMATION,
                explanation="Introduction acknowledged; asked the scenario's question.",
                rule_ids=("fallback.clarify", "clarify.ask_after_intro"),
            )
        return CallerDecision(
            message=phrases.clarify,
            intent=CallerIntent.CLARIFY,
            next_state=CallerState.SEEKING_CLARIFICATION,
            explanation="Bot's answer was not usable; asked for clarification.",
            rule_ids=("fallback.clarify",),
        )

    # -- Provider interface -------------------------------------------------

    async def decide(self, context: CallerContext) -> CallerDecision:
        """Choose the caller's next utterance by first matching rule."""
        signals = analyse(
            context.bot_transcript,
            language=context.persona.language,
            known_facts=context.known_facts,
        )
        for rule in self._rules:
            if rule.matches(context, signals):
                return rule.decide(context, signals)
        # Unreachable: `fallback.clarify` matches unconditionally. Kept so the
        # function has no implicit `None` return if the rule set is edited.
        raise AssertionError("no rule matched; the fallback rule is missing")

    async def close(self) -> None:
        """Nothing to release."""
        return None


__all__ = ["PROVIDER_NAME", "DeterministicCallerProvider"]
