/**
 * Copy and status data for the public site.
 *
 * Typed constants rather than API reads, deliberately: the landing page
 * describes the *project* — what is built, what is partial — and no endpoint
 * serves that. The workspace at `/app` is where live server state belongs,
 * and it fetches everything it shows.
 *
 * **Every claim here is checkable against the repository.** `phases` is the
 * original fifteen-phase table from README.md, CLAUDE.md and
 * docs/DEVELOPMENT_ROADMAP.md, and `tests/content.test.mjs` fails when the
 * two disagree, so this page cannot quietly fall behind the project again.
 * (It once said "Phase 8 of 15" for a week after Phase 14 closed, because the
 * number was typed in by hand, in the competition's renumbered scheme.)
 */

export const site = {
  name: "BhashaBench",
  tagline: "Does your voice AI actually understand India?",
  description:
    "Test Indian-language voice AI under real-world conversational conditions — " +
    "from code-mixing and interruptions to noisy environments.",
  repository: "https://github.com/YushBytes/BhashaBench",
} as const;

/** Status vocabulary, matching the badges used across the product. */
export type Status = "built" | "partial" | "planned";

export interface Phase {
  readonly number: number;
  readonly title: string;
  readonly status: Status;
  readonly note?: string;
}

/** The original numbering, 1 to 15 (Phase 0 was remediation, not product). */
export const phases: readonly Phase[] = [
  { number: 1, title: "Project foundation", status: "built" },
  { number: 2, title: "Database & scenario engine", status: "built" },
  { number: 3, title: "Scenario library & tooling", status: "built" },
  {
    number: 4,
    title: "Speech to text (Gnani Prisma)",
    status: "built",
    note: "Batch live-verified; streaming not live-verified.",
  },
  {
    number: 5,
    title: "Text to speech (Gnani Timbre)",
    status: "built",
    note: "Batch; streaming synthesis not implemented.",
  },
  {
    number: 6,
    title: "AI caller simulation — Evon",
    status: "partial",
    note:
      "The rule engine is delivered. A Sarvam language-model caller is built and " +
      "tested offline; live calls are not authorised. Gnani Evon is not " +
      "integrated: no text-generation endpoint is published.",
  },
  {
    number: 7,
    title: "Audio degradation engine",
    status: "built",
    note: "Synthetic noise and channel conditions; no recorded noise beds.",
  },
  {
    number: 8,
    title: "Telephony integration",
    status: "partial",
    note:
      "Provider abstraction, guardrails, signed webhooks and a mocked provider. " +
      "No real telephone call has been placed or authorised.",
  },
  {
    number: 9,
    title: "Real-time conversation engine",
    status: "built",
    note:
      "Streaming turn-taking, barge-in detection and recovery, verified against " +
      "the reference bot. Speech is still recognised per utterance.",
  },
  {
    number: 10,
    title: "Recording & transcription",
    status: "built",
    note: "Local storage; recordings are assembled from turn audio, not captured live.",
  },
  {
    number: 11,
    title: "Evaluation & judge engine",
    status: "built",
    note:
      "Deterministic: WER, CER, task completion, latency. The LLM judge is " +
      "offline-only and not validated against human labels.",
  },
  {
    number: 12,
    title: "Reporting & analytics backend",
    status: "built",
    note: "Aggregates with intervals, comparison, regression and CSV/JSON export; no PDF.",
  },
  { number: 13, title: "Frontend dashboard", status: "built" },
  {
    number: 14,
    title: "CI/CD & safety",
    status: "built",
    note:
      "Authentication, tenancy, rate limits, security headers, dependency and " +
      "secret scanning, a regression gate.",
  },
  {
    number: 15,
    title: "Production readiness",
    status: "partial",
    note:
      "Production images, backup and restore, and a zero-cost local stack verified " +
      "end to end. Not publicly deployed.",
  },
] as const;

export const totalPhases = phases.length;
export const completedPhases = phases.filter((p) => p.status === "built").length;
export const partialPhases = phases.filter((p) => p.status === "partial").map((p) => p.number);

/** The hero badge: derived from the table, never typed in. */
export const statusBadge =
  `${completedPhases} of ${totalPhases} phases complete · ` +
  `${partialPhases.length} partial · no telephone call placed`;

/** The steps a run actually performs, in order. */
export const workflow = [
  {
    step: "Select a scenario",
    detail:
      "A persona, an objective, known facts the caller may quote, and the " +
      "acoustic environment the test assumes. Authored as YAML, or loaded from " +
      "the reference library.",
  },
  {
    step: "Generate caller speech",
    detail:
      "The configured text-to-speech provider synthesises the caller's turn — " +
      "Gnani Timbre, or the offline fake, which every run names in its evidence.",
  },
  {
    step: "Apply acoustic conditions",
    detail:
      "Band-limiting, background noise at a measured signal-to-noise ratio, a " +
      "G.711 codec, jitter, dropouts, clipping and truncation. Reproducible from " +
      "a fixed seed.",
  },
  {
    step: "Exchange with the bot",
    detail:
      "A scripted fixture, a reply an operator uploads, or a real external bot " +
      "over HTTP text or a streaming voice WebSocket.",
  },
  {
    step: "Transcribe the reply",
    detail:
      "The configured speech-to-text provider turns the bot's audio into text. " +
      "A transcription failure is recorded as a failure, never as silence.",
  },
  {
    step: "Continue the conversation",
    detail:
      "The caller decides the next turn from what the bot actually said, and the " +
      "loop repeats until the goal or the turn budget ends it.",
  },
  {
    step: "Evaluate and compare",
    detail:
      "Task completion, required and forbidden phrases, latency, and WER/CER " +
      "against reviewed reference transcripts — then analytics, comparison, " +
      "regression checks and export.",
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
      "locale. Ten are transcribable and speakable with Gnani; Urdu, Odia and " +
      "Assamese are authorable and not yet covered by a provider.",
    status: "built",
    phase: 3,
  },
  {
    title: "Gnani Prisma and Timbre",
    summary:
      "Speech to text and text to speech behind provider-independent interfaces. " +
      "Confidence and word timings stay empty because Prisma does not report " +
      "them — not defaulted to a number that would read as certainty.",
    status: "built",
    phase: 4,
  },
  {
    title: "Goal-driven caller",
    summary:
      "A caller that pursues an objective rather than replaying a script. The " +
      "deterministic rule engine always produces the same turn from the same " +
      "context, which is what makes a benchmark reproducible.",
    status: "partial",
    phase: 6,
  },
  {
    title: "Audio degradation",
    summary:
      "Noise scaled from each utterance's own RMS so the stated ratio holds, with " +
      "the achieved ratio asserted to better than 0.5 dB. The original always " +
      "survives beside the processed file.",
    status: "built",
    phase: 7,
  },
  {
    title: "External bots, text and voice",
    summary:
      "Two published protocols: text over HTTP, and real-time voice over a " +
      "WebSocket with 20 ms frames, barge-in and end-of-turn detection. A run " +
      "records whether every reply genuinely came from outside the process.",
    status: "built",
    phase: 9,
  },
  {
    title: "Evaluation, analytics and comparison",
    summary:
      "Deterministic verdicts with their reasons, pass rates with confidence " +
      "intervals and n, run-to-run comparison, a regression check, and CSV and " +
      "JSON export.",
    status: "built",
    phase: 11,
  },
] as const;

/** Stated plainly, because the product is a measurement instrument. */
export const limitations = [
  {
    title: "No telephone call has been placed",
    detail:
      "Telephony exists as a provider abstraction with a mocked provider. " +
      "`telephony_test` is excluded from the modes a run can be created in — an " +
      "unusable enum member is the honest record of the gap.",
  },
  {
    title: "Gnani Evon is not integrated",
    detail:
      "No text-generation endpoint is published for it and the released model " +
      "has no hosted inference provider. The caller is a rule engine, named for " +
      "what it is; configuring `evon` fails with an error explaining why.",
  },
  {
    title: "Only the reference bot has been tested end to end",
    detail:
      "The HTTP and voice adapters are verified against the repository's own " +
      "reference bot, a separate process with scripted replies. No production " +
      "voice bot has been run through them yet.",
  },
  {
    title: "A local demo uses offline speech providers",
    detail:
      "Without Gnani credentials, transcripts are scripted by an offline fake and " +
      "every run says so (`stt_provider: fake`). No accuracy figure from such a " +
      "run describes any real speech engine.",
  },
] as const;

/**
 * The language catalogue, as the public site shows it. Copied from
 * backend/app/core/languages.py (the single source of truth) because the
 * public page is static and must render with no backend; `tests/content.test.mjs`
 * reads that file and fails when this list disagrees with it.
 *
 * `transcribable` is Prisma's coverage as docs/PROVIDERS.md states it: ten of
 * the thirteen. Authorable is not the same as transcribable.
 */
export const languages = [
  { code: "hi-IN", name: "Hindi", endonym: "हिन्दी", script: "Deva", transcribable: true },
  { code: "bn-IN", name: "Bengali", endonym: "বাংলা", script: "Beng", transcribable: true },
  { code: "mr-IN", name: "Marathi", endonym: "मराठी", script: "Deva", transcribable: true },
  { code: "te-IN", name: "Telugu", endonym: "తెలుగు", script: "Telu", transcribable: true },
  { code: "ta-IN", name: "Tamil", endonym: "தமிழ்", script: "Taml", transcribable: true },
  { code: "gu-IN", name: "Gujarati", endonym: "ગુજરાતી", script: "Gujr", transcribable: true },
  { code: "ur-IN", name: "Urdu", endonym: "اردو", script: "Arab", transcribable: false },
  { code: "kn-IN", name: "Kannada", endonym: "ಕನ್ನಡ", script: "Knda", transcribable: true },
  { code: "or-IN", name: "Odia", endonym: "ଓଡ଼ିଆ", script: "Orya", transcribable: false },
  { code: "ml-IN", name: "Malayalam", endonym: "മലയാളം", script: "Mlym", transcribable: true },
  { code: "pa-IN", name: "Punjabi", endonym: "ਪੰਜਾਬੀ", script: "Guru", transcribable: true },
  { code: "as-IN", name: "Assamese", endonym: "অসমীয়া", script: "Beng", transcribable: false },
  { code: "en-IN", name: "Indian English", endonym: "Indian English", script: "Latn", transcribable: true },
] as const;

/** Feature status as the public site states it. `limited` names what is missing. */
export type FeatureStatus = "built" | "limited";

export const features: readonly {
  key: string;
  title: string;
  body: string;
  status: FeatureStatus;
  limit?: string;
}[] = [
  {
    key: "languages",
    title: "Indian-language callers",
    body: "A goal-driven caller speaks reviewed phrase tables in the scenario's language and pursues its objective turn by turn.",
    status: "limited",
    limit: "A deterministic rule engine. Bengali, Marathi and Telugu phrase tables are not written yet.",
  },
  {
    key: "conditions",
    title: "Line and room conditions",
    body: "G.711 A-law and µ-law, jitter, dropouts, clipping, gain, truncation, silence and noise at a stated signal-to-noise ratio, from a fixed seed.",
    status: "built",
  },
  {
    key: "accent",
    title: "Accent profiles",
    body: "A scenario requests an accent from the catalogue and every run records whether the speech provider applied it.",
    status: "limited",
    limit: "No speech provider documents an accented voice, so runs record it as requested, not applied.",
  },
  {
    key: "barge-in",
    title: "Caller interruption",
    body: "The caller talks over the bot a set time into its reply, and the run records whether the bot stopped and how fast.",
    status: "limited",
    limit: "Only on the streaming voice adapter (ws_voice). Sequential adapters cannot interrupt.",
  },
  {
    key: "code-mixing",
    title: "Code-mixing measurement",
    body: "Every turn is split into runs of one writing system, and WER is reported per script, so you see where English words inside Tamil were lost.",
    status: "limited",
    limit: "Measured as script switching. The caller's own speech is monolingual for now.",
  },
  {
    key: "wer",
    title: "Speech recognition error rates",
    body: "Word and character error rates against a reviewer's reference transcript, never against the transcript being scored.",
    status: "built",
  },
  {
    key: "evaluation",
    title: "Conversation verdicts",
    body: "Task completion, required and forbidden phrases, latency and transcription failures, each verdict with its reason.",
    status: "built",
  },
  {
    key: "comparison",
    title: "Comparison and regression",
    body: "Two runs side by side with metric deltas, and a Fisher exact test between two periods before anything is called a regression.",
    status: "built",
  },
  {
    key: "reports",
    title: "Evidence you can export",
    body: "Each run's turns, recordings, stage timings and evaluation as JSON, CSV or a printable PDF.",
    status: "built",
  },
];

/**
 * Qualities the evaluator does not measure. They need the LLM judge, which is
 * offline-only and not validated against human labels (docs/EVALUATION.md),
 * so they are shown as unavailable and never scored.
 */
export const unmeasuredQualities = [
  "Semantic correctness",
  "Context retention",
  "Response relevance",
  "Language quality",
] as const;

export const unmeasuredReason =
  "These need a language-model judge. BhashaBench's judge runs offline only and has not been " +
  "validated against human labels, so these qualities are reported as unavailable rather than scored.";

const DOCS = "https://github.com/YushBytes/BhashaBench/blob/main/docs";

/** Documentation that exists in the repository. */
export const docs = [
  { title: "Scenario format", href: `${DOCS}/SCENARIO_FORMAT.md`, body: "Every field a scenario takes, with its bounds." },
  { title: "Bot protocol", href: `${DOCS}/BOT_PROTOCOL.md`, body: "Connect a bot over HTTP text or streaming voice." },
  { title: "Evaluation", href: `${DOCS}/EVALUATION.md`, body: "How each metric and verdict is computed." },
  { title: "Local deployment", href: `${DOCS}/LOCAL_DEPLOYMENT.md`, body: "Run the whole stack on one machine at no cost." },
] as const;
