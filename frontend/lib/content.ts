/**
 * Copy and status data for the public site.
 *
 * Typed constants rather than API reads, deliberately: the landing page
 * describes the *project* — what is built, what is partial, what is not
 * started — and no endpoint serves that. The workspace at `/app` is where
 * live server state belongs, and it fetches everything it shows.
 *
 * **Every claim here is checkable against the repository.** When a phase's
 * status changes, this file and the phase tables in README.md, CLAUDE.md
 * and docs/DEVELOPMENT_ROADMAP.md change together; they are the first thing
 * a reader checks to learn what actually works.
 */

export const site = {
  name: "BhashaBench",
  tagline: "Does your voice AI actually understand India?",
  description:
    "Test Indian-language voice AI under real-world conversational conditions — " +
    "from code-mixing and interruptions to noisy environments.",
  repository: "https://github.com/YushBytes/BhashaBench",
} as const;

export const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const currentPhase = 8;
export const totalPhases = 15;

/** Status vocabulary, matching the badges used across the product. */
export type Status = "built" | "partial" | "planned";

export interface Phase {
  readonly number: number;
  readonly title: string;
  readonly status: Status;
  readonly note?: string;
}

export const phases: readonly Phase[] = [
  { number: 1, title: "Project foundation", status: "built" },
  { number: 2, title: "Data model and persistence", status: "built" },
  { number: 3, title: "Scenario definition format", status: "built" },
  { number: 4, title: "Speech to text (Gnani Prisma)", status: "built" },
  { number: 5, title: "Text to speech (Gnani Timbre)", status: "built" },
  {
    number: 6,
    title: "Caller simulation",
    status: "partial",
    note:
      "The rule engine is complete. Gnani Evon is not integrated: no " +
      "text-generation endpoint is published and the released model has no " +
      "hosted inference provider.",
  },
  {
    number: 7,
    title: "End-to-end voice pipeline",
    status: "partial",
    note:
      "Runs end to end offline. No live provider call and no real voice bot " +
      "has gone through it.",
  },
  {
    number: 8,
    title: "Operator workspace",
    status: "partial",
    note: "This interface. Run history, conversation inspector and audio playback.",
  },
  { number: 9, title: "Telephony and media streaming", status: "planned" },
  { number: 10, title: "Conversation orchestration", status: "planned" },
  { number: 11, title: "Automated evaluation and scoring", status: "planned" },
  { number: 12, title: "Multilingual benchmarking", status: "planned" },
  { number: 13, title: "Results API and reporting", status: "planned" },
  { number: 14, title: "CI regression testing", status: "planned" },
  { number: 15, title: "Hardening, observability and release", status: "planned" },
] as const;

/** The seven steps a run actually performs, in order. */
export const workflow = [
  {
    step: "Select a scenario",
    detail:
      "A persona, an objective, known facts the caller may quote, and the " +
      "acoustic environment the test assumes. Authored as YAML.",
  },
  {
    step: "Generate caller speech",
    detail:
      "Gnani Timbre synthesises the caller's turn at 8 kHz — the rate an " +
      "Indian phone call actually runs at.",
  },
  {
    step: "Apply acoustic conditions",
    detail:
      "Band-limiting, background noise at a measured signal-to-noise ratio, " +
      "clipping and packet loss. Reproducible from a fixed seed.",
  },
  {
    step: "Supply the bot's reply",
    detail:
      "A scripted fixture, or audio an operator captured from the bot under " +
      "test and posted back.",
  },
  {
    step: "Transcribe with Prisma",
    detail:
      "Gnani Prisma turns the bot's audio into text. A transcription failure " +
      "is recorded as a failure, never as silence.",
  },
  {
    step: "Continue the conversation",
    detail:
      "The caller's state machine decides the next turn from what the bot " +
      "actually said, and the loop repeats until the goal or the budget ends it.",
  },
  {
    step: "Inspect the evidence",
    detail:
      "Every turn, both audio variants, each pipeline stage with its measured " +
      "duration, and the outcome the run reached.",
  },
] as const;

/** What exists, with the phase that delivered it. */
export interface Capability {
  readonly title: string;
  readonly summary: string;
  readonly status: Status;
  readonly phase: number;
}

export const capabilities: readonly Capability[] = [
  {
    title: "Indian-language scenarios",
    summary:
      "Thirteen languages in the catalogue, each with its endonym, script and " +
      "locale. Ten are transcribable and speakable today; Urdu, Odia and " +
      "Assamese are authorable and not yet covered by a provider.",
    status: "built",
    phase: 3,
  },
  {
    title: "Gnani Prisma transcription",
    summary:
      "Batch and streaming speech to text behind a provider-independent " +
      "interface. Confidence and word timings stay empty because Prisma does " +
      "not report them — not defaulted to a number that would read as certainty.",
    status: "built",
    phase: 4,
  },
  {
    title: "Gnani Timbre synthesis",
    summary:
      "Thirteen documented voices across ten languages, at telephony sample " +
      "rates. Every returned file's rate and duration is read from the bytes, " +
      "never echoed back from the request.",
    status: "built",
    phase: 5,
  },
  {
    title: "Deterministic caller",
    summary:
      "A caller that pursues a goal rather than replaying a script, driven by " +
      "a state machine and reviewed phrase tables. The same context always " +
      "produces the same turn, which is what makes a benchmark reproducible.",
    status: "partial",
    phase: 6,
  },
  {
    title: "Audio degradation",
    summary:
      "Noise scaled from each utterance's own RMS so the stated ratio holds, " +
      "with the achieved ratio asserted to better than 0.5 dB. The original " +
      "always survives beside the processed file.",
    status: "partial",
    phase: 7,
  },
  {
    title: "Multi-turn pipeline",
    summary:
      "Caller, synthesis, degradation, bot exchange, transcription and the " +
      "next decision, each stage timed. Outcomes are structured; none of them " +
      "is a score.",
    status: "partial",
    phase: 7,
  },
] as const;

/** Stated plainly, because the product is a measurement instrument. */
export const limitations = [
  {
    title: "Gnani Evon is not integrated",
    detail:
      "No text-generation endpoint is published for it and the released model " +
      "has no hosted inference provider. The caller is a rule engine, named " +
      "for what it is. Configuring `evon` as a provider fails with an error " +
      "explaining why.",
  },
  {
    title: "No telephone call has been placed",
    detail:
      "There is no telephony or SIP integration. `telephony_test` exists in " +
      "the execution-mode enum and is excluded from the set a run can be " +
      "created in — an unusable enum member is the honest record of the gap.",
  },
  {
    title: "No real external bot has been tested end to end",
    detail:
      "Both shipping bot adapters are offline. One replays fixture audio; the " +
      "other waits for an operator to supply the bot's reply by hand. A run " +
      "reports whether every reply genuinely came from outside the process, " +
      "so a mislabelled test is visible.",
  },
  {
    title: "Nothing here is an accuracy score",
    detail:
      "There is no word error rate, no accuracy figure and no quality verdict, " +
      "because none is computable without a reviewed reference transcript. " +
      "The pipeline measures and counts; evaluation is a later phase.",
  },
] as const;
