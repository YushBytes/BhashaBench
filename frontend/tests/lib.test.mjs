// Frontend unit tests for lib/: run with `npm test` (node --test, Node 24
// strips TypeScript types natively, so no test framework is added).
//
// What these pin: the formatters never turn "no data" into a number, the
// sign-in redirect cannot leave the site, and the API client builds the
// requests it claims to - same-origin credentials, dropped empty query
// values, the error envelope's message, and no fallback data on failure.

import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";

import { ApiError, api, artefactAudioUrl, recordingAudioUrl, request } from "../lib/api/client.ts";
import { formatErrorRate, formatPassRate, humanise, shortId } from "../lib/format.ts";
import { safeNext } from "../lib/redirect.ts";

describe("formatPassRate", () => {
  it("states the rate with its interval and n", () => {
    assert.equal(
      formatPassRate({ rate: 0.8, ci95_low: 0.4902, ci95_high: 0.9433, n: 10 }),
      "80% (49%–94%), n = 10",
    );
  });

  it("returns null when nothing was decided - never 0%", () => {
    assert.equal(formatPassRate({ rate: null, ci95_low: null, ci95_high: null, n: 0 }), null);
    assert.equal(formatPassRate({ rate: 0, ci95_low: 0, ci95_high: 0.3, n: 0 }), null);
  });

  it("keeps a real zero", () => {
    assert.equal(formatPassRate({ rate: 0, ci95_low: 0, ci95_high: 0.2775, n: 10 }), "0% (0%–28%), n = 10");
  });
});

describe("other formatters", () => {
  it("formatErrorRate refuses missing and non-finite values", () => {
    assert.equal(formatErrorRate(0.125), "12.5%");
    assert.equal(formatErrorRate(null), null);
    assert.equal(formatErrorRate(Number.NaN), null);
  });

  it("humanise and shortId", () => {
    assert.equal(humanise("no_significant_difference"), "No significant difference");
    assert.equal(shortId("12345678-aaaa-bbbb-cccc-dddddddddddd").length <= 12, true);
  });
});

describe("safeNext", () => {
  for (const ok of ["/app", "/app/runs", "/app/runs/abc?x=1", "/app?tab=1"]) {
    it(`follows ${ok}`, () => assert.equal(safeNext(ok), ok));
  }
  for (const bad of [null, "", "https://evil.example/app", "//evil.example/app", "/\\evil.example", "/appevil", "/login", "javascript:alert(1)"]) {
    it(`refuses ${String(bad)}`, () => assert.equal(safeNext(bad), "/app"));
  }
});

describe("audio URLs", () => {
  it("are relative, so the session cookie travels with them", () => {
    assert.equal(artefactAudioUrl("r1", 3, null), "/api/v1/test-runs/r1/artifacts/3/audio");
    assert.equal(artefactAudioUrl("r1", 3, "degraded"), "/api/v1/test-runs/r1/artifacts/3/audio?variant=degraded");
    assert.equal(recordingAudioUrl("r1"), "/api/v1/test-runs/r1/recording/audio");
  });
});

describe("request", () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  function stub(response) {
    const calls = [];
    globalThis.fetch = async (url, init) => {
      calls.push({ url: String(url), init });
      if (response instanceof Error) throw response;
      return response;
    };
    return calls;
  }

  it("builds the URL, drops empty query values and sends same-origin credentials", async () => {
    const calls = stub(new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
    const body = await request("/api/v1/test-runs", {
      query: { limit: 5, status: undefined, mode: null, scenario: "" },
      headers: { cookie: "bb_session=x" },
    });
    assert.deepEqual(body, { ok: 1 });
    const url = new URL(calls[0].url);
    assert.equal(url.pathname, "/api/v1/test-runs");
    assert.deepEqual([...url.searchParams.keys()], ["limit"]);
    assert.equal(calls[0].init.credentials, "same-origin");
    assert.equal(calls[0].init.headers.cookie, "bb_session=x");
  });

  it("sends a JSON body with its content type", async () => {
    const calls = stub(new Response(JSON.stringify({}), { status: 200 }));
    await api.login("a@b.test", "pw");
    assert.equal(calls[0].init.method, "POST");
    assert.equal(calls[0].init.headers["content-type"], "application/json");
    assert.deepEqual(JSON.parse(calls[0].init.body), { email: "a@b.test", password: "pw", session_type: "cookie" });
  });

  it("reads and records a bot turn's reference transcript at the evaluation route", async () => {
    const calls = stub(new Response(JSON.stringify({ references: [] }), { status: 200 }));
    await api.turnReferences("r1", 3);
    assert.equal(new URL(calls[0].url).pathname, "/api/v1/test-runs/r1/turns/3/reference");
    assert.equal(calls[0].init.method ?? "GET", "GET");

    const saved = stub(new Response(JSON.stringify({ reference_id: "x" }), { status: 201 }));
    await api.addTurnReference("r1", 3, { text: "policy number please" });
    assert.equal(new URL(saved[0].url).pathname, "/api/v1/test-runs/r1/turns/3/reference");
    assert.equal(saved[0].init.method, "POST");
    assert.deepEqual(JSON.parse(saved[0].init.body), { text: "policy number please" });
  });

  it("surfaces the API's error message and status, with no fallback data", async () => {
    stub(new Response(JSON.stringify({ error: { type: "unauthenticated", message: "no valid session", status_code: 401 } }), { status: 401 }));
    await assert.rejects(request("/api/v1/auth/me"), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.kind, "http");
      assert.equal(error.status, 401);
      assert.equal(error.type, "unauthenticated");
      assert.equal(error.message, "no valid session");
      assert.equal(error.retryable, false);
      return true;
    });
  });

  it("tells a network failure from an HTTP one", async () => {
    stub(new TypeError("fetch failed"));
    await assert.rejects(request("/api/v1/health"), (error) => error instanceof ApiError && error.kind === "network" && error.retryable);
  });

  it("reports its own deadline as a timeout", async () => {
    globalThis.fetch = (_url, init) =>
      new Promise((_resolve, reject) => init.signal.addEventListener("abort", () => reject(init.signal.reason)));
    // AbortSignal.timeout's timer is unreferenced: with nothing else pending,
    // Node 22 exits the loop before it fires. A browser or the Next server
    // never does, so the test keeps the loop alive rather than the client
    // changing its timer.
    const keepAlive = setTimeout(() => {}, 5_000);
    try {
      await assert.rejects(
        request("/api/v1/health", { timeoutMs: 20 }),
        (error) => error instanceof ApiError && error.kind === "timeout",
      );
    } finally {
      clearTimeout(keepAlive);
    }
  });

  it("returns undefined for 204", async () => {
    stub(new Response(null, { status: 204 }));
    assert.equal(await api.logout(), undefined);
  });
});

describe("metricRows", async () => {
  const { metricRows } = await import("../lib/evaluation.ts");

  it("formats measured WER and CER with what they rest on", () => {
    const rows = metricRows({
      wer: { value: 0.384615, errors: 5, scored_turns: 1, reference_length: 13 },
      cer: { value: 0.446154, errors: 29, scored_turns: 1, reference_length: 65 },
    });
    assert.equal(rows[0].value, "38.5%");
    assert.match(rows[0].detail, /1 bot turn scored against a reviewed reference, 5 errors in 13/);
    assert.equal(rows[1].value, "44.6%");
  });

  it("never turns an unmeasured metric into zero", () => {
    const rows = metricRows({
      wer: { value: null, reason: "no bot turn has a reviewed reference transcript", scored_turns: 0 },
      bot_response_latency_ms: { value: null, samples: 0, reason: "no bot turn carries a measured latency" },
      transcription_failure_rate: { value: null, reason: "no bot audio was transcribed in this run" },
    });
    for (const row of rows) assert.equal(row.value, null, row.key);
    assert.equal(rows[0].detail, "no bot turn has a reviewed reference transcript");
    assert.equal(rows[1].detail, "no bot turn carries a measured latency");
  });

  it("keeps a real zero and states latency percentiles", () => {
    const rows = metricRows({
      transcription_failure_rate: { value: 0, failed: 0, bot_turns: 4 },
      bot_response_latency_ms: { p50: 312.4, p90: 480.9, max: 500, samples: 3 },
    });
    assert.equal(rows[0].value, "p50 312 ms · p90 481 ms");
    assert.equal(rows[1].value, "0.0%");
    assert.equal(rows[1].detail, "0 of 4 bot turns not transcribed");
  });

  it("labels keyword coverage as an indicator, not a judgement", () => {
    const [row] = metricRows({ expected_outcome_keyword_coverage: { value: 0.5, covered: 2, declared: 4 } });
    assert.equal(row.value, "50%");
    assert.match(row.detail, /not a judgement/);
  });
});
