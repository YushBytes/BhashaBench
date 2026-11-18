/**
 * Response shapes from the BhashaBench API.
 *
 * Transcribed from the backend's Pydantic models, field for field. Three
 * rules this file exists to keep:
 *
 * 1. **No field appears here that the API does not return.** A plausible
 *    field the UI could use is how fabricated data gets into an interface.
 * 2. **Optional means optional.** Where the backend returns `null` because a
 *    provider does not report something - `confidence`, `segments`,
 *    `sample_rate_hz` for a container we cannot inspect - the type is
 *    `| null` and the UI must render "not reported", never a number.
 * 3. **The honesty fields are not optional to render.** `uses_language_model`,
 *    `bot_audio_externally_received`, `evon_status`, `telephony_status` and
 *    `measurement_note` exist so a client cannot overclaim. They are typed as
 *    required because the components that show them are required.
 */

// ---------------------------------------------------------------------------
// Enumerations
// ---------------------------------------------------------------------------

export type ExecutionMode =
  | "offline_simulation"
  | "audio_fixture_test"
  | "external_bot_test"
  | "text_bot_test"
  | "telephony_test";

export type PipelineStatus =
  | "created"
  | "initializing"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "timed_out";

export type RunOutcome =
  | "goal_achieved"
  | "bot_refused"
  | "bot_unintelligible"
  | "no_progress"
  | "turn_budget_exhausted"
  | "provider_error"
  | "audio_validation_failed"
  | "external_bot_unavailable"
  | "bot_protocol_error"
  | "bot_ended_session"
  | "cancelled"
  | "abandoned";

export type CallerState =
  | "initial"
  | "introducing"
  | "awaiting_information"
  | "providing_details"
  | "seeking_clarification"
  | "confirming"
  | "goal_achieved"
  | "failed"
  | "terminated";

export type CallerIntent =
  | "open"
  | "ask"
  | "provide_fact"
  | "clarify"
  | "repeat_request"
  | "correct"
  | "decline_unknown"
  | "confirm"
  | "close";

export type TerminationReason =
  | "goal_achieved"
  | "turn_budget_exhausted"
  | "bot_refused"
  | "no_progress"
  | "bot_unintelligible"
  | "provider_error"
  | "operator_terminated"
  | "cancelled";

export type NoiseProfile =
  | "clean"
  | "light_background_noise"
  | "moderate_background_noise"
  | "heavy_background_noise"
  | "telephony_bandwidth";

export type HealthStatus = "ok" | "degraded" | "unavailable";

export type ArtefactVariant = "original" | "degraded";

// ---------------------------------------------------------------------------
// Envelopes
// ---------------------------------------------------------------------------

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ErrorDetail {
  type: string;
  message: string;
  status_code: number;
}

export interface ErrorEnvelope {
  error: ErrorDetail;
}

// ---------------------------------------------------------------------------
// Health and languages
// ---------------------------------------------------------------------------

export interface ComponentHealth {
  name: string;
  status: HealthStatus;
  detail: string;
}

export interface ApiHealth {
  status: HealthStatus;
  service: string;
  version: string;
  api_version: string;
  environment: string;
  timestamp: string;
  uptime_seconds: number;
  components: ComponentHealth[];
}

export interface Language {
  code: string;
  name: string;
  endonym: string;
  script: string;
  locale: string;
}

export interface LanguageCatalogue {
  languages: Language[];
  total: number;
}

// ---------------------------------------------------------------------------
// Suites and scenarios
// ---------------------------------------------------------------------------

/** `GET /suites` items. No `scenario_count`: only the detail route
 *  (`GET /suites/{id}`) returns one, and this type once claimed it. */
export interface SuiteSummary {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

// -- Authentication (Phase 14) -----------------------------------------------

export type Role = "owner" | "admin" | "member" | "viewer";

export interface SessionUser {
  id: string;
  email: string;
  display_name: string;
}

/** `POST /auth/login` with `session_type: "cookie"`: `token` is always null,
 *  because the token is set as an HttpOnly cookie and never shown to script. */
export interface LoginResult {
  user: SessionUser;
  expires_at: string;
  session_type: "cookie" | "bearer";
  token: string | null;
}

export interface Me {
  user: SessionUser;
  workspaces: {
    workspace_id: string;
    workspace_name: string;
    workspace_slug: string;
    role: Role;
  }[];
  session_expires_at: string | null;
}

export interface ScenarioSummary {
  id: string;
  suite_id: string;
  name: string;
  description: string | null;
  language: string;
  created_at: string;
  updated_at: string;
}

/** The parts of a scenario specification the UI reads. */
export interface ScenarioSpec {
  name: string;
  description: string | null;
  language: string;
  persona?: {
    identity?: string;
    speaking_style?: string;
    traits?: string[];
  } | null;
  goal?: {
    objective?: string;
    max_turns?: number;
  } | null;
  known_facts?: Record<string, string> | null;
  expected_outcomes?: string[] | null;
  audio?: {
    noise_profile?: string;
    snr_db?: number | null;
    packet_loss_percent?: number | null;
  } | null;
}

export interface ScenarioDetail extends ScenarioSummary {
  spec: ScenarioSpec;
  spec_version: number;
}

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------

export interface TranscriptionProvider {
  name: string;
  display_name: string;
  selected: boolean;
  available: boolean;
  unavailable_reason: string | null;
  languages: string[];
  unsupported_catalogue_languages: string[];
  modes: string[];
  supports_batch: boolean;
  supports_streaming: boolean;
  supports_partial_results: boolean;
  supports_confidence: boolean;
  supports_word_timestamps: boolean;
  supports_diarisation: boolean;
  max_batch_bytes: number | null;
  max_batch_duration_seconds: number | null;
  requires_credentials: boolean;
  notes: string[];
}

export interface TranscriptionProviders {
  selected: string;
  providers: TranscriptionProvider[];
}

export interface Voice {
  name: string;
  gender: string | null;
  character: string | null;
}

export interface SpeechProvider {
  name: string;
  display_name: string;
  selected: boolean;
  available: boolean;
  unavailable_reason: string | null;
  languages: string[];
  extra_language_values: string[];
  unsupported_catalogue_languages: string[];
  voices: Voice[];
  voices_are_exhaustive: boolean;
  models: string[];
  default_model: string;
  containers: string[];
  sample_rates: number[];
  supports_audio_tags: boolean;
  supports_streaming: boolean;
  max_text_chars: number | null;
  requires_credentials: boolean;
  serialises_requests: boolean;
  notes: string[];
}

export interface SpeechProviders {
  selected: string;
  providers: SpeechProvider[];
}

export interface CallerProvider {
  name: string;
  display_name: string;
  selected: boolean;
  available: boolean;
  unavailable_reason: string | null;
  is_deterministic: boolean;
  uses_language_model: boolean;
  languages: string[];
  supports_code_mixing: boolean;
  requires_credentials: boolean;
  max_turns_supported: number | null;
  notes: string[];
}

export interface CallerProviders {
  selected: string;
  providers: CallerProvider[];
  /** Stated on the API surface so a client cannot mistake the rule engine
   *  for Gnani Evon. Rendered verbatim. */
  evon_status: string;
}

export interface BotAdapter {
  name: string;
  display_name: string;
  selected: boolean;
  contacts_external_system: boolean;
  /** Whether this deployment has configured what the adapter needs. */
  available: boolean;
  /** Which setting is missing when unavailable. Names settings, never values. */
  unavailable_reason: string | null;
  supports_sessions: boolean;
  requires_credentials: boolean;
  accepts_containers: string[];
  notes: string[];
}

export interface BotAdapters {
  selected: string;
  adapters: BotAdapter[];
  /** Rendered verbatim. */
  telephony_status: string;
  /** Modes a run may actually be created in. The new-test form offers
   *  exactly these and nothing else. */
  execution_modes: string[];
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export interface RunSummary {
  run_id: string;
  suite_id: string;
  scenario_name: string;
  language: string;
  mode: ExecutionMode;
  status: PipelineStatus;
  outcome: RunOutcome | null;
  noise_profile: string | null;
  bot_adapter: string | null;
  bot_audio_externally_received: boolean;
  bot_exchange: string | null;
  bot_text_externally_received: boolean;
  uses_language_model: boolean;
  caller_turns: number;
  bot_turns: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  error: string | null;
}

/** A scenario setting the run declares and nothing in it enforces. */
export interface SettingNotEnforced {
  /** Dotted path in the scenario, e.g. `constraints.allow_interruptions`. */
  setting: string;
  declared: unknown;
  reason: string;
}

/** What each degraded caller turn was asked for (requested, not achieved). */
export interface DegradationRequested {
  source: "scenario" | "operator";
  /** `null` when no noise is requested. */
  snr_db: number | null;
  packet_loss_percent: number;
}

export interface Run {
  run_id: string;
  suite_id: string;
  conversation_id: string | null;
  scenario_name: string;
  language: string;
  mode: ExecutionMode;
  status: PipelineStatus;
  outcome: RunOutcome | null;
  caller_provider: string;
  uses_language_model: boolean;
  stt_provider: string | null;
  tts_provider: string | null;
  bot_adapter: string;
  bot_audio_externally_received: boolean;
  /** `text` for a text_bot_test, `audio`, or `null` for an offline simulation. */
  bot_exchange: string | null;
  /** True only when a text_bot_test recorded a reply from the external bot.
   *  Counted from the replies, never read from the mode. */
  bot_text_externally_received: boolean;
  bot_text_replies_received: number;
  bot_session_id: string | null;
  bot_greeting: string | null;
  noise_profile: NoiseProfile;
  scenario_noise_profile: string | null;
  degradation_seed: number | null;
  caller_turns: number;
  bot_turns: number;
  bot_transcripts_succeeded: number;
  bot_transcripts_failed: number;
  turn_budget: number;
  caller_state: CallerState;
  termination_reason: TerminationReason | null;
  goal_achieved: boolean;
  total_audio_seconds: number;
  /** `null` for runs created before it was recorded: unknown, not "all enforced". */
  settings_not_enforced: SettingNotEnforced[] | null;
  /** `null` for runs that move no audio and for runs created before it was recorded. */
  degradation_requested: DegradationRequested | null;
  /** Offline run with the manual adapter, waiting for `POST /bot-text`. */
  awaiting_bot_text_for_turn: number | null;
  awaiting_bot_audio_for_turn: number | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface RunTurn {
  index: number;
  speaker: string;
  /** `null` for a bot turn whose audio could not be transcribed. Deliberately
   *  distinct from `""`, which means the bot said nothing. */
  text: string | null;
  intent: string | null;
  state_before: string | null;
  state_after: string | null;
  rule_ids: string[];
  audio_reference: string | null;
  transcription_error: string | null;
  synthesis_error: string | null;
}

export interface RunTurns {
  run_id: string;
  turns: RunTurn[];
}

export interface Artefact {
  turn_index: number;
  speaker: string;
  variant: ArtefactVariant | null;
  reference: string;
  size_bytes: number;
  content_type: string;
  sample_rate_hz: number | null;
  channels: number | null;
  duration_seconds: number | null;
  derived_from: string | null;
  transformations: string[];
  degradation_parameters: Record<string, unknown>;
  seed: number | null;
}

export interface RunArtefacts {
  run_id: string;
  artefacts: Artefact[];
  total_audio_seconds: number;
}

export interface StageEvent {
  turn_index: number;
  stage: string;
  status: string;
  duration_ms: number | null;
  detail: string | null;
  /** Structured detail where a stage has it - a streaming bot turn's
   *  `ended_by`, `bot_latency_ms`, `barge_in` (Phase 9). Null otherwise. */
  evidence?: Record<string, unknown> | null;
}

export interface RunReport {
  run: Run;
  state_transitions: Array<Record<string, unknown>>;
  artefacts: Artefact[];
  events: StageEvent[];
  /** Stated by the API so counts are not mistaken for a quality score.
   *  Rendered wherever counts appear. */
  measurement_note: string;
}

export interface CreateRunBody {
  suite_id: string;
  scenario_id: string;
  mode: ExecutionMode;
  noise_profile?: NoiseProfile | null;
  seed?: number | null;
  max_turns?: number | null;
  degrade_caller_audio?: boolean;
  bot_adapter?: string | null;
}

// -- Analytics (Phase 12) - transcribed from backend/app/analytics/service.py -

/** A pass rate: pass / (pass + fail), with its Wilson 95% interval. `rate`
 *  and the bounds are null when no run was decided (n = 0), never zero. */
export interface PassRate {
  successes: number;
  n: number;
  rate: number | null;
  ci95_low: number | null;
  ci95_high: number | null;
  interval: "wilson";
}

export interface VerdictTally {
  runs: number;
  verdicts: { pass: number; fail: number; undetermined: number; not_evaluated: number };
  pass_rate: PassRate;
}

export type AnalyticsDimension =
  | "language"
  | "scenario_name"
  | "bot_adapter"
  | "mode"
  | "outcome"
  | "suite_id";

export interface AnalyticsSummary {
  filter: Record<string, string>;
  group_by: AnalyticsDimension | null;
  overall: VerdictTally;
  groups: (VerdictTally & { key: string | null })[];
  metrics: {
    wer_pooled: {
      value: number | null;
      errors: number;
      reference_words: number;
      runs_with_references: number;
    };
    per_run_median_latency_ms: {
      p50: number | null;
      p90: number | null;
      runs: number;
      note: string;
    };
  };
  evaluator_versions: string[];
  warnings: string[];
}

export interface AnalyticsTrend {
  filter: Record<string, string>;
  bucket: "day" | "week";
  periods: (VerdictTally & { period: string })[];
  evaluator_versions: string[];
  warnings: string[];
}

export interface ComparedRun {
  run_id: string;
  scenario_name: string | null;
  language: string | null;
  mode: string | null;
  bot_adapter: string | null;
  evaluator_version: string;
  evidence_fingerprint: string;
  verdict: "pass" | "fail" | "undetermined";
}

export interface RunComparison {
  baseline: ComparedRun;
  candidate: ComparedRun;
  verdict_change: "regressed" | "improved" | "unchanged" | "not_comparable";
  metric_deltas: {
    metric: string;
    baseline: number | null;
    candidate: number | null;
    delta: number | null;
    change: "better" | "worse" | "unchanged" | "not_comparable";
  }[];
  comparable: boolean;
  warnings: string[];
  statistical_note: string;
}

export interface RegressionResult {
  baseline: VerdictTally & { filter: Record<string, string> };
  candidate: VerdictTally & { filter: Record<string, string> };
  pass_rate_difference: number | null;
  test: "fisher_exact_two_sided";
  p_value: number | null;
  alpha: number;
  min_decided_runs_per_group: number;
  conclusion: "regression" | "improvement" | "no_significant_difference" | "insufficient_evidence";
  reason: string;
  evaluator_versions: string[];
  warnings: string[];
}

// -- Workspaces (Phase 14) - transcribed from backend/app/schemas/auth.py ----

export interface WorkspaceRead {
  id: string;
  name: string;
  slug: string;
  /** The caller's own role here. */
  role: Role;
  created_at: string;
}

export interface MemberRead {
  user_id: string;
  email: string;
  display_name: string;
  role: Role;
}

export interface ProjectRead {
  id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  created_at: string;
}

// -- Evaluation and recording (Phases 10-11) ---------------------------------

export interface EvaluationRead {
  evaluation_id: string;
  run_id: string;
  evaluator_version: string;
  verdict: "pass" | "fail" | "undetermined";
  evidence_fingerprint: string;
  created_at: string;
  /** Every criterion has at least these; some carry more detail. */
  criteria: { name: string; status: string; reason: string }[];
  metrics: Record<string, unknown>;
  /** False for text and offline modes: nothing here describes audio. */
  measures_audio: boolean;
}

export interface EvaluationList {
  run_id: string;
  evaluations: EvaluationRead[];
}

/** `POST /test-runs/{id}/turns/{i}/reference`: reviewed ground truth for one
 *  bot turn, the input WER and CER need. Append-only; the newest is used. */
export interface ReferenceRead {
  reference_id: string;
  run_id: string;
  turn_index: number;
  text: string;
  reviewer: string | null;
  created_at: string;
}

/** `GET /test-runs/{id}/turns/{i}/reference`: oldest first; the last is used. */
export interface ReferenceHistory {
  run_id: string;
  turn_index: number;
  references: ReferenceRead[];
}

/** `GET /test-runs/{id}/recording`. Fields beyond `status` are present only
 *  when the backend set them; `reason` explains a failed or absent one. */
export interface RecordingManifest {
  status: "stored" | "failed" | "not_applicable";
  reason?: string;
  duration_seconds?: number;
  segments?: { turn_index: number; speaker: string; variant: string | null; start_seconds: number; duration_seconds: number }[];
  excluded?: { turn_index: number; speaker: string; reason: string }[];
  assembly?: string;
}

// -- Suite and scenario authoring (Phases 2-3) -------------------------------

export interface ScenarioValidation {
  /** HTTP 200 either way: `valid` carries the verdict. */
  valid: boolean;
  errors: { field: string; message: string; type: string }[];
  normalized_yaml: string | null;
}
