"""Every metric BhashaBench reports, defined once.

A metric that is not in this registry is not reported. Each definition says
what it measures, from which evidence, how it is computed, which direction is
better, what happens when the evidence is missing, and what it cannot tell
you - the API serves these verbatim (`GET /api/v1/evaluation/metrics`), so a
number on a report can always be traced to its definition.

There is deliberately **no composite score**. Task completion, phrase
compliance, error rates and latency measure different things on different
scales, and a weighted sum would let a fast bot that fails the task look
better than a slow one that succeeds. A run's verdict is a conjunction of
named pass/fail criteria instead, each with its own reasoning.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.evaluation.text import NORMALISATION_VERSION

EVALUATOR_VERSION = "bb-eval-2"
"""Bumped whenever a definition, a formula or a criterion changes, so two
evaluations are comparable only when their versions match.

bb-eval-1 -> bb-eval-2 added `script_mixing` and `wer_by_script` and put the
caller's utterances into the evidence (which changes its fingerprint). No
existing metric's formula changed."""


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    title: str
    definition: str
    formula: str
    evidence: str
    normalisation: str
    better: str
    """`lower`, `higher`, `pass` for a boolean criterion, or `neither` for a
    descriptive measurement that is part of no verdict."""
    missing_data: str
    limitations: tuple[str, ...]
    unit: str

    def as_dict(self) -> dict[str, object]:
        out = asdict(self)
        out["limitations"] = list(self.limitations)
        return out


METRICS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        name="task_completion",
        title="Task completion",
        definition="Whether the caller achieved its scenario objective.",
        formula="1 if the run's outcome is goal_achieved, else 0.",
        evidence="The run's recorded outcome, which the caller's state machine sets.",
        normalisation="None.",
        better="pass",
        missing_data=(
            "Undetermined - not 0 - when the run is unfinished or ended for a reason "
            "that says nothing about the bot (provider_error, audio_validation_failed, "
            "external_bot_unavailable, cancelled, abandoned)."
        ),
        limitations=(
            "'Achieved' is the deterministic caller's judgement from keyword and "
            "digit signals in the bot's words, not a semantic understanding.",
        ),
        unit="boolean",
    ),
    MetricDefinition(
        name="required_phrases",
        title="Required phrases present",
        definition="Every phrase the scenario requires appears in at least one bot turn.",
        formula="pass if each normalised phrase is a substring of the normalised bot text.",
        evidence="Bot turns' text: transcripts in audio modes, replies in text modes.",
        normalisation=NORMALISATION_VERSION,
        better="pass",
        missing_data="Not evaluated when the scenario declares no required phrases.",
        limitations=(
            "Exact phrase match after normalisation: a paraphrase does not count.",
            "In audio modes this measures the transcript, so a recognition error "
            "can fail a bot that said the phrase.",
        ),
        unit="boolean",
    ),
    MetricDefinition(
        name="forbidden_phrases",
        title="Forbidden phrases absent",
        definition="No phrase the scenario forbids appears in any bot turn.",
        formula="pass if no normalised phrase is a substring of any normalised bot turn.",
        evidence="Bot turns' text.",
        normalisation=NORMALISATION_VERSION,
        better="pass",
        missing_data="Not evaluated when the scenario declares no forbidden phrases.",
        limitations=("Exact phrase match after normalisation; a paraphrase is not caught.",),
        unit="boolean",
    ),
    MetricDefinition(
        name="expected_outcome_keyword_coverage",
        title="Expected-outcome keyword coverage",
        definition=(
            "The fraction of the scenario's expected outcomes whose content words all "
            "appear somewhere in the bot's turns."
        ),
        formula="covered outcomes / declared outcomes; content words are tokens of 3+ chars.",
        evidence="Bot turns' text and the scenario's expected_outcomes.",
        normalisation=NORMALISATION_VERSION,
        better="higher",
        missing_data="Not evaluated when the scenario declares no expected outcomes.",
        limitations=(
            "A keyword indicator, not a semantic judgement: it is fooled by a bot "
            "that mentions the words while saying something else, and misses a "
            "correct answer phrased differently. Never part of the verdict.",
            "Expected outcomes are usually written in English while the bot speaks "
            "the scenario's language, which this cannot bridge.",
        ),
        unit="ratio",
    ),
    MetricDefinition(
        name="wer",
        title="Word error rate",
        definition="Recognition errors in bot transcripts against reviewed references.",
        formula="(substitutions + deletions + insertions) / reference words.",
        evidence=(
            "Each bot turn's transcript and its reviewed reference transcript. Only "
            "turns with a reference are scored; the count of scored turns is reported."
        ),
        normalisation=NORMALISATION_VERSION,
        better="lower",
        missing_data="Null when no bot turn has a reviewed reference. Never estimated.",
        limitations=(
            "Number words versus numerals score as errors (no number normalisation).",
            "Text written in another script scores as fully wrong; nothing is transliterated.",
            "Pooled over turns: total errors / total reference words, not a mean of rates.",
        ),
        unit="ratio",
    ),
    MetricDefinition(
        name="cer",
        title="Character error rate",
        definition="Character-level recognition errors against reviewed references.",
        formula="(S + D + I) / reference grapheme clusters, spaces excluded.",
        evidence="As for WER.",
        normalisation=NORMALISATION_VERSION,
        better="lower",
        missing_data="Null when no bot turn has a reviewed reference.",
        limitations=(
            "Clusters are a base character and its combining marks; conjuncts are "
            "not merged into aksharas.",
        ),
        unit="ratio",
    ),
    MetricDefinition(
        name="bot_response_latency_ms",
        title="Bot response latency",
        definition="How long the bot took to answer each turn.",
        formula="p50, p90 and max over bot turns with a measured latency_ms.",
        evidence=(
            "latency_ms on each bot turn, measured with a monotonic clock around the "
            "bot request. Recorded by the http adapter; fixture and manual replies "
            "have none."
        ),
        normalisation="None.",
        better="lower",
        missing_data="Null when no bot turn carries a measured latency. Never estimated.",
        limitations=(
            "Measures the HTTP exchange from this process, network included; not "
            "time-to-first-audio, which needs streaming (Phase 9).",
            "Percentiles over few turns are unstable; the sample size is reported.",
        ),
        unit="milliseconds",
    ),
    MetricDefinition(
        name="transcription_failure_rate",
        title="Transcription failure rate",
        definition="The share of bot turns whose audio we could not transcribe.",
        formula="bot turns with a transcription_error / bot turns.",
        evidence="Bot turns' metadata in audio modes.",
        normalisation="None.",
        better="lower",
        missing_data="Not evaluated in text modes, which transcribe nothing.",
        limitations=("Our failure, not the bot's: never part of the bot's verdict.",),
        unit="ratio",
    ),
    MetricDefinition(
        name="script_mixing",
        title="Script switching (observable code-mixing)",
        definition=(
            "For the caller's and the bot's turns: how many turns switch writing "
            "system mid-utterance, how many switches there are, and words per script."
        ),
        formula=(
            "Each word takes the ISO 15924 script of most of its letters; consecutive "
            "words of one script form a segment; switches = segments - 1 per turn."
        ),
        evidence="Caller turn text and bot transcripts.",
        normalisation="None; words are whitespace-separated.",
        better="neither",
        missing_data="Zero turns when a side said nothing; never a guessed value.",
        limitations=(
            "Script is not language: Hindi and Marathi share Devanagari, and "
            "romanised Hindi is Latin, indistinguishable from English.",
            "A transcriber writing an English loanword in an Indic script hides the switch.",
            "Descriptive, not a score: it is part of no verdict.",
        ),
        unit="count",
    ),
    MetricDefinition(
        name="wer_by_script",
        title="Word error rate by script",
        definition=(
            "WER computed separately over the reference words written in each "
            "script, against the hypothesis words in the same script."
        ),
        formula=(
            "For each script in a turn's reference: WER(reference words in that "
            "script, transcript words in that script); errors and reference "
            "lengths pooled across scored turns."
        ),
        evidence="Reviewed reference transcripts and the bot transcripts they score.",
        normalisation="bb-norm-1, as for WER.",
        better="lower",
        missing_data="Null, with the reason, when no bot turn has a reference.",
        limitations=(
            "A word transcribed in the wrong script counts as a deletion in one "
            "script and an insertion in another.",
            "Inherits every limitation of script_mixing.",
        ),
        unit="ratio per script",
    ),
)

BY_NAME = {m.name: m for m in METRICS}

__all__ = ["BY_NAME", "EVALUATOR_VERSION", "METRICS", "MetricDefinition"]
