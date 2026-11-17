/**
 * The one place the frontend talks to the API.
 *
 * Every call goes through `request`, so timeouts, the error envelope and the
 * "backend is not running" case are handled once rather than per page.
 *
 * **There is no mock mode and no fallback data.** A failed call surfaces as
 * an `ApiError` the UI renders as an error state. Returning plausible-looking
 * data when the backend is unreachable would make a broken deployment look
 * like a working one, which is the single thing this product may not do.
 *
 * **Sessions (Phase 14).** The browser talks only to its own origin: Next
 * rewrites `/api/v1/*` to the backend (`next.config.ts`), so the API's
 * HttpOnly session cookie is first-party and is sent automatically - this
 * module never sees the token. On the server, `lib/api/server.ts` reads the
 * cookie from the incoming request and passes it in `headers`; it calls no
 * route itself.
 */

import type {
  AnalyticsSummary,
  AnalyticsTrend,
  ApiHealth,
  BotAdapters,
  CallerProviders,
  CreateRunBody,
  EvaluationList,
  EvaluationRead,
  LanguageCatalogue,
  LoginResult,
  Me,
  MemberRead,
  Page,
  ProjectRead,
  RecordingManifest,
  RegressionResult,
  Role,
  Run,
  RunComparison,
  RunArtefacts,
  RunReport,
  RunSummary,
  RunTurns,
  ScenarioDetail,
  ScenarioSummary,
  SpeechProviders,
  SuiteSummary,
  TranscriptionProviders,
  WorkspaceRead,
} from "./types";

/** Where the backend lives, from the Next server's point of view. The
 *  browser never uses this: it calls its own origin and the rewrite proxies. */
export const BACKEND_URL =
  process.env.BACKEND_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://localhost:8000";

function base(): string {
  return typeof window === "undefined" ? BACKEND_URL : window.location.origin;
}

const DEFAULT_TIMEOUT_MS = 15_000;

/**
 * A failed API call, carrying enough for the UI to say something true.
 *
 * `kind` separates the three failures that look alike in a `catch` and need
 * different words on screen: the server answered with an error, the server
 * could not be reached at all, or we gave up waiting.
 */
export class ApiError extends Error {
  readonly kind: "http" | "network" | "timeout";
  readonly status: number | null;
  readonly type: string | null;

  constructor(
    message: string,
    options: {
      kind: "http" | "network" | "timeout";
      status?: number | null;
      type?: string | null;
    },
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = options.kind;
    this.status = options.status ?? null;
    this.type = options.type ?? null;
  }

  /** Whether retrying the same request could plausibly succeed. */
  get retryable(): boolean {
    if (this.kind !== "http") return true;
    return this.status === null || this.status >= 500;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Query parameters. Undefined and null entries are dropped rather than
   *  sent as the strings "undefined" and "null". */
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Next.js fetch caching. Server components pass a revalidate window;
   *  client components pass `no-store`. */
  cache?: RequestCache;
  revalidate?: number;
  /** Extra request headers. Server pages pass the session cookie here. */
  headers?: Record<string, string>;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(path.replace(/^\//, ""), `${base().replace(/\/$/, "")}/`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/** Pull the message out of the API's uniform error envelope. */
async function describeFailure(response: Response): Promise<ApiError> {
  let message = `The API returned ${response.status}.`;
  let type: string | null = null;
  try {
    const body = (await response.json()) as unknown;
    if (
      body &&
      typeof body === "object" &&
      "error" in body &&
      body.error &&
      typeof body.error === "object"
    ) {
      const detail = body.error as { message?: string; type?: string };
      if (detail.message) message = detail.message;
      if (detail.type) type = detail.type;
    }
  } catch {
    // A non-JSON error body is not itself an error worth reporting; the
    // status code is still the useful part.
  }
  return new ApiError(message, { kind: "http", status: response.status, type });
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const {
    method = "GET",
    body,
    signal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    query,
    cache,
    revalidate,
    headers: extraHeaders,
  } = options;

  // Our own deadline, combined with any caller-supplied signal, so a slow
  // backend cannot leave a page spinning forever.
  const timer = AbortSignal.timeout(timeoutMs);
  const composed = signal ? AbortSignal.any([signal, timer]) : timer;

  const init: RequestInit & { next?: { revalidate: number } } = {
    method,
    signal: composed,
    headers: {
      ...(body ? { "content-type": "application/json" } : {}),
      ...extraHeaders,
    },
    // Same-origin in the browser; the session cookie travels by itself.
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  };
  if (cache) init.cache = cache;
  if (revalidate !== undefined) init.next = { revalidate };

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), init);
  } catch (cause) {
    if (timer.aborted) {
      throw new ApiError(
        `The API did not respond within ${Math.round(timeoutMs / 1000)} seconds.`,
        { kind: "timeout" },
      );
    }
    if (signal?.aborted) throw cause;
    throw new ApiError(
      `Could not reach the API at ${base()}. Is the backend running?`,
      { kind: "network" },
    );
  }

  if (!response.ok) throw await describeFailure(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// ---------------------------------------------------------------------------
// Endpoints
//
// One function per route, named for what it fetches. No function here
// invents a path: each corresponds to a route in the generated OpenAPI
// document.
// ---------------------------------------------------------------------------

export const api = {
  login: (email: string, password: string, o?: RequestOptions) =>
    request<LoginResult>("/api/v1/auth/login", {
      ...o,
      method: "POST",
      // `cookie`: the token is set HttpOnly and never returned to script.
      body: { email, password, session_type: "cookie" },
    }),

  logout: (o?: RequestOptions) =>
    request<void>("/api/v1/auth/logout", { ...o, method: "POST" }),

  me: (o?: RequestOptions) => request<Me>("/api/v1/auth/me", o),

  health: (o?: RequestOptions) => request<ApiHealth>("/api/v1/health", o),

  languages: (o?: RequestOptions) =>
    request<LanguageCatalogue>("/api/v1/languages", o),

  suites: (o?: RequestOptions) =>
    request<Page<SuiteSummary>>("/api/v1/suites", { ...o, query: { limit: 100, ...o?.query } }),

  scenarios: (o?: RequestOptions) =>
    request<Page<ScenarioSummary>>("/api/v1/scenarios", o),

  scenario: (id: string, o?: RequestOptions) =>
    request<ScenarioDetail>(`/api/v1/scenarios/${id}`, o),

  transcriptionProviders: (o?: RequestOptions) =>
    request<TranscriptionProviders>("/api/v1/transcription/providers", o),

  speechProviders: (o?: RequestOptions) =>
    request<SpeechProviders>("/api/v1/speech/providers", o),

  callerProviders: (o?: RequestOptions) =>
    request<CallerProviders>("/api/v1/caller/providers", o),

  botAdapters: (o?: RequestOptions) =>
    request<BotAdapters>("/api/v1/test-runs/bot-adapters/available", o),

  runs: (o?: RequestOptions) =>
    request<Page<RunSummary>>("/api/v1/test-runs", o),

  run: (id: string, o?: RequestOptions) =>
    request<Run>(`/api/v1/test-runs/${id}`, o),

  runTurns: (id: string, o?: RequestOptions) =>
    request<RunTurns>(`/api/v1/test-runs/${id}/turns`, o),

  runArtefacts: (id: string, o?: RequestOptions) =>
    request<RunArtefacts>(`/api/v1/test-runs/${id}/artifacts`, o),

  runReport: (id: string, o?: RequestOptions) =>
    request<RunReport>(`/api/v1/test-runs/${id}/report`, o),

  createRun: (body: CreateRunBody, o?: RequestOptions) =>
    request<Run>("/api/v1/test-runs", { ...o, method: "POST", body }),

  startRun: (id: string, o?: RequestOptions) =>
    request<Run>(`/api/v1/test-runs/${id}/start`, {
      ...o,
      method: "POST",
      // A run executes turns through synthesis, degradation and
      // transcription. The default deadline is for reading a row.
      timeoutMs: o?.timeoutMs ?? 120_000,
    }),

  runEvaluations: (id: string, o?: RequestOptions) =>
    request<EvaluationList>(`/api/v1/test-runs/${id}/evaluations`, o),

  evaluateRun: (id: string, o?: RequestOptions) =>
    request<EvaluationRead>(`/api/v1/test-runs/${id}/evaluations`, { ...o, method: "POST" }),

  runRecording: (id: string, o?: RequestOptions) =>
    request<RecordingManifest>(`/api/v1/test-runs/${id}/recording`, o),

  workspaces: (o?: RequestOptions) => request<WorkspaceRead[]>("/api/v1/workspaces", o),

  members: (workspaceId: string, o?: RequestOptions) =>
    request<MemberRead[]>(`/api/v1/workspaces/${workspaceId}/members`, o),

  addMember: (workspaceId: string, email: string, role: Role, o?: RequestOptions) =>
    request<MemberRead>(`/api/v1/workspaces/${workspaceId}/members`, {
      ...o,
      method: "POST",
      body: { email, role },
    }),

  changeRole: (workspaceId: string, userId: string, role: Role, o?: RequestOptions) =>
    request<MemberRead>(`/api/v1/workspaces/${workspaceId}/members/${userId}`, {
      ...o,
      method: "PATCH",
      body: { role },
    }),

  removeMember: (workspaceId: string, userId: string, o?: RequestOptions) =>
    request<void>(`/api/v1/workspaces/${workspaceId}/members/${userId}`, {
      ...o,
      method: "DELETE",
    }),

  projects: (workspaceId: string, o?: RequestOptions) =>
    request<ProjectRead[]>(`/api/v1/workspaces/${workspaceId}/projects`, o),

  createProject: (workspaceId: string, name: string, o?: RequestOptions) =>
    request<ProjectRead>(`/api/v1/workspaces/${workspaceId}/projects`, {
      ...o,
      method: "POST",
      body: { name },
    }),

  analyticsSummary: (o?: RequestOptions) =>
    request<AnalyticsSummary>("/api/v1/analytics/summary", o),

  analyticsTrend: (o?: RequestOptions) => request<AnalyticsTrend>("/api/v1/analytics/trend", o),

  compareRuns: (baseline: string, candidate: string, o?: RequestOptions) =>
    request<RunComparison>("/api/v1/analytics/compare", {
      ...o,
      query: { baseline, candidate },
    }),

  regressions: (o?: RequestOptions) =>
    request<RegressionResult>("/api/v1/analytics/regressions", o),

  cancelRun: (id: string, o?: RequestOptions) =>
    request<Run>(`/api/v1/test-runs/${id}/cancel`, { ...o, method: "POST" }),
};

/**
 * The URL that streams one stored artefact.
 *
 * Built here rather than in a component so the shape of the route lives with
 * the rest of the client. Note it addresses the artefact by turn and variant:
 * the stored reference never travels in a request.
 */
export function artefactAudioUrl(
  runId: string,
  turnIndex: number,
  variant: string | null,
): string {
  // Relative, so the browser requests it from this origin with the session
  // cookie; an absolute backend URL would be a cross-site request without it.
  const path = `/api/v1/test-runs/${runId}/artifacts/${turnIndex}/audio`;
  return variant ? `${path}?variant=${encodeURIComponent(variant)}` : path;
}

/** The full-conversation recording, relative so the cookie travels with it. */
export function recordingAudioUrl(runId: string): string {
  return `/api/v1/test-runs/${runId}/recording/audio`;
}
