// The "Connect your chatbot" rules against the backend they mirror.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  MAX_TOKEN_CHARS,
  MAX_URL_CHARS,
  MIN_TOKEN_CHARS,
  NOT_CARRIED,
  OUTCOMES,
  SCHEMES,
  isPlainTransport,
  tokenProblem,
  urlProblem,
  validateDraft,
} from "../lib/integration.ts";

const SERVICE = readFileSync(new URL("../../backend/app/services/integration_service.py", import.meta.url), "utf8");
const PROBE = readFileSync(new URL("../../backend/app/pipeline/bots/probe.py", import.meta.url), "utf8");

const constant = (name) => Number(SERVICE.match(new RegExp(`^${name} = (\\d+)`, "m"))?.[1]);

describe("transcribed from the backend", () => {
  it("uses the server's token and URL bounds", () => {
    assert.equal(MIN_TOKEN_CHARS, constant("MIN_TOKEN_CHARS"));
    assert.equal(MAX_TOKEN_CHARS, constant("MAX_TOKEN_CHARS"));
    assert.equal(MAX_URL_CHARS, constant("MAX_URL_CHARS"));
  });

  it("accepts exactly the server's schemes per protocol", () => {
    const http = SERVICE.match(/IntegrationProtocol\.HTTP: frozenset\(\{([^}]*)\}\)/)[1];
    const ws = SERVICE.match(/IntegrationProtocol\.WS_VOICE: frozenset\(\{([^}]*)\}\)/)[1];
    const names = (text) => [...text.matchAll(/"([a-z]+)"/g)].map((m) => m[1]).sort();
    assert.deepEqual([...SCHEMES.http].sort(), names(http));
    assert.deepEqual([...SCHEMES.ws_voice].sort(), names(ws));
  });

  it("has words for every outcome a check can return, and no others", () => {
    const block = PROBE.slice(PROBE.indexOf("class ProbeOutcome"), PROBE.indexOf("@dataclass"));
    const outcomes = [...block.matchAll(/^    [A-Z_]+ = "([a-z_]+)"/gm)].map((m) => m[1]).sort();
    assert.deepEqual(Object.keys(OUTCOMES).sort(), outcomes);
  });

  it("marks as not carried only what the text protocol records as false", () => {
    const block = PROBE.slice(PROBE.indexOf("HTTP_UNVERIFIED"), PROBE.indexOf('"""The text protocol'));
    const falses = [...block.matchAll(/"([a-z_]+)": False/g)].map((m) => m[1]).sort();
    assert.deepEqual([...NOT_CARRIED.http].sort(), falses);
  });
});

describe("validateDraft", () => {
  const ok = { name: "Support bot", protocol: "http", url: "https://bot.example.com", token: "a".repeat(20) };

  it("accepts a well-formed draft", () => {
    assert.deepEqual(validateDraft(ok), {});
  });

  it("refuses a scheme the protocol cannot use", () => {
    assert.match(urlProblem("http", "wss://bot.example.com"), /https:\/\/ or http:\/\//);
    assert.match(urlProblem("ws_voice", "https://bot.example.com"), /wss:\/\/ or ws:\/\//);
  });

  it("refuses a credential or a fragment in the URL", () => {
    assert.match(urlProblem("http", "https://admin:pw@bot.example.com"), /username or password/);
    assert.match(urlProblem("http", "https://bot.example.com/#x"), /fragment/);
    assert.match(urlProblem("http", "bot.example.com"), /not a complete URL/);
  });

  it("refuses a short token or one with whitespace, without quoting it", () => {
    const short = tokenProblem("short");
    assert.match(short, /16 to 4096/);
    assert.ok(!short.includes("short"));
    assert.match(tokenProblem("has a space inside it ok"), /no spaces/);
  });

  it("lets an edit omit the token", () => {
    assert.deepEqual(validateDraft({ ...ok, token: "" }, { tokenRequired: false }), {});
    assert.ok(validateDraft({ ...ok, token: "" }).token);
  });

  it("notices plain transport so the form can warn about it", () => {
    assert.equal(isPlainTransport("http://127.0.0.1:8090"), true);
    assert.equal(isPlainTransport("ws://127.0.0.1:8090/v1/voice"), true);
    assert.equal(isPlainTransport("https://bot.example.com"), false);
  });
});
