/**
 * Single source of truth for the copy and status data rendered by the shell.
 *
 * Kept as typed constants rather than fetched from the API on purpose: the
 * endpoints that would serve roadmap and capability data do not exist yet,
 * and inventing a client for them would mean shipping a fake integration.
 * Phase 13 replaces this module with real data from the results API.
 */

export const site = {
  name: "BhashaBench",
  tagline: "Test your voice AI before India tests it for you.",
  description:
    "An automated testing and benchmarking platform for Indian-language voice bots. " +
    "Simulated callers, realistic audio degradation and automated conversation scoring.",
  repository: "https://github.com/YushBytes/BhashaBench",
} as const;

/** Where the FastAPI backend is reachable from the browser. */
export const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * Status vocabulary, used consistently everywhere in the UI.
 * `live` is reserved for behaviour that genuinely works today.
 */
export type Status = "live" | "partial" | "planned";

export const statusLabel: Record<Status, string> = {
  live: "Live",
  partial: "Partial",
  planned: "Planned",
};

export interface Phase {
  readonly number: number;
  readonly title: string;
  readonly status: Status;
}

export const currentPhase = 7;
export const totalPhases = 15;

export const phases: readonly Phase[] = [
  { number: 1, title: "Project foundation", status: "live" },
  { number: 2, title: "Data model & persistence", status: "live" },
  { number: 3, title: "Scenario definition format", status: "live" },
  { number: 4, title: "Speech to text (Gnani Prisma)", status: "live" },
  { number: 5, title: "Text to speech (Gnani Timbre)", status: "live" },
  // "Partial", not "live": the caller engine is complete and the Gnani Evon
  // integration the phase was scoped around is not, because no documented
  // API access exists. Marking this "live" would be the claim the first rule
  // in CLAUDE.md forbids.
  { number: 6, title: "Caller simulation (rule-based)", status: "partial" },
  // "Partial", not "live": the pipeline runs end to end offline, and no real
  // voice bot or live provider call has gone through it.
  { number: 7, title: "End-to-end voice pipeline", status: "partial" },
  { number: 8, title: "Twilio telephony & media streaming", status: "planned" },
  { number: 9, title: "Conversation orchestration engine", status: "planned" },
  { number: 10, title: "Automated evaluation & scoring", status: "planned" },
  { number: 11, title: "Multilingual benchmarking", status: "planned" },
  { number: 12, title: "Results API & reporting", status: "planned" },
  { number: 13, title: "React dashboard", status: "planned" },
  { number: 14, title: "CI regression testing", status: "planned" },
  { number: 15, title: "Hardening, observability & release", status: "planned" },
] as const;

/** What the finished test suite will do. Every entry is labelled honestly. */
export interface Capability {
  readonly title: string;
  readonly summary: string;
  readonly status: Status;
  readonly phase: number;
}

export const capabilities: readonly Capability[] = [
  {
    title: "Simulated callers",
    summary:
      "A caller that pursues a goal instead of replaying a script, projected from the scenario's persona. Deterministic and rule-based: Gnani Evon is not integrated, because no documented API access exists.",
    status: "partial",
    phase: 6,
  },
  {
    title: "Realistic audio degradation",
    summary:
      "Band-limiting, background noise at a measured signal-to-noise ratio, clipping and packet loss, applied from a seed so every run reproduces exactly. Simulated conditions, not field recordings.",
    status: "partial",
    phase: 7,
  },
  {
    title: "Live telephony",
    summary:
      "Outbound calls over Twilio with bidirectional media streaming, barge-in handling and a hard allow-list on dialable numbers.",
    status: "planned",
    phase: 8,
  },
  {
    title: "Automated scoring",
    summary:
      "Per-criterion pass/fail with reasoning, alongside deterministic metrics: latency percentiles, word error rate and task completion.",
    status: "planned",
    phase: 10,
  },
  {
    title: "Multilingual benchmarks",
    summary:
      "Suites spanning ten Indian languages plus code-mixed speech, normalised per language so scores stay comparable.",
    status: "planned",
    phase: 11,
  },
  {
    title: "Regression testing in CI",
    summary:
      "Every pull request runs the suite against the sample bot and fails when conversation quality drops below the baseline.",
    status: "planned",
    phase: 14,
  },
] as const;

/**
 * The service-level endpoints, listed because they take no arguments and so
 * are the quickest check that a deployment is alive. This is deliberately a
 * subset: the API serves 41 operations across 34 paths, and the full list
 * belongs in the generated OpenAPI document rather than being duplicated —
 * and drifting — here. Re-derive the totals with
 * `create_app().openapi()["paths"]` when they are quoted in copy.
 */
export interface Endpoint {
  readonly method: "GET";
  readonly path: string;
  readonly summary: string;
}

export const endpoints: readonly Endpoint[] = [
  { method: "GET", path: "/", summary: "Service identity and version" },
  { method: "GET", path: "/health", summary: "Liveness probe" },
  {
    method: "GET",
    path: "/api/v1/health",
    summary: "Structured per-subsystem health",
  },
] as const;

export const navigation = [
  { label: "Overview", href: "#overview" },
  { label: "Test suite", href: "#test-suite" },
  { label: "API", href: "#api" },
  { label: "Roadmap", href: "#roadmap" },
] as const;
