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
 */

import type {
  ApiHealth,
  BotAdapters,
  CallerProviders,
  CreateRunBody,
  LanguageCatalogue,
  Page,
  Run,
  RunArtefacts,
  RunReport,
  RunSummary,
  RunTurns,
  ScenarioDetail,
  ScenarioSummary,
  SpeechProviders,
  SuiteSummary,
  TranscriptionProviders,
} from "./types";

/** Where the API lives, from the browser's point of view. */
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(path.replace(/^\//, ""), `${API_BASE.replace(/\/$/, "")}/`);
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
  } = options;

  // Our own deadline, combined with any caller-supplied signal, so a slow
  // backend cannot leave a page spinning forever.
  const timer = AbortSignal.timeout(timeoutMs);
  const composed = signal ? AbortSignal.any([signal, timer]) : timer;

  const init: RequestInit & { next?: { revalidate: number } } = {
    method,
    signal: composed,
    headers: body ? { "content-type": "application/json" } : undefined,
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
      `Could not reach the API at ${API_BASE}. Is the backend running?`,
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
  const url = new URL(
    `api/v1/test-runs/${runId}/artifacts/${turnIndex}/audio`,
    `${API_BASE.replace(/\/$/, "")}/`,
  );
  if (variant) url.searchParams.set("variant", variant);
  return url.toString();
}
