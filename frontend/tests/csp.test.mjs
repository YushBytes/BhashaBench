// The page Content-Security-Policy (lib/csp.ts) and the proxy that sets it.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { contentSecurityPolicy, newNonce } from "../lib/csp.ts";

const directives = (policy) =>
  Object.fromEntries(
    policy.split("; ").map((part) => {
      const [name, ...sources] = part.split(" ");
      return [name, sources];
    }),
  );

describe("newNonce", () => {
  it("is 128 random bits, base64-encoded", () => {
    const nonce = newNonce();
    assert.match(nonce, /^[A-Za-z0-9+/]{22}==$/);
    assert.equal(Buffer.from(nonce, "base64").length, 16);
  });

  it("is different on every request", () => {
    const seen = new Set(Array.from({ length: 2000 }, () => newNonce()));
    assert.equal(seen.size, 2000);
  });
});

describe("contentSecurityPolicy", () => {
  const nonce = newNonce();
  const prod = directives(contentSecurityPolicy(nonce));
  const dev = directives(contentSecurityPolicy(nonce, { dev: true }));

  it("allows scripts only by nonce, never inline or eval in production", () => {
    assert.deepEqual(prod["script-src"], ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'"]);
    for (const sources of Object.values(prod)) {
      assert.ok(!sources.includes("'unsafe-eval'"));
    }
    assert.ok(!prod["script-src"].includes("'unsafe-inline'"));
    assert.ok(!prod["style-src"].includes("'unsafe-inline'"));
  });

  it("adds eval only in development, where React's dev build needs it", () => {
    assert.ok(dev["script-src"].includes("'unsafe-eval'"));
  });

  it("keeps the documented exception narrow: inline style attributes only", () => {
    assert.deepEqual(prod["style-src"], ["'self'", `'nonce-${nonce}'`]);
    assert.deepEqual(prod["style-src-attr"], ["'unsafe-inline'"]);
  });

  it("locks down plugins, framing, base and form targets, and connects only to this origin", () => {
    assert.deepEqual(prod["object-src"], ["'none'"]);
    assert.deepEqual(prod["frame-ancestors"], ["'none'"]);
    assert.deepEqual(prod["base-uri"], ["'self'"]);
    assert.deepEqual(prod["form-action"], ["'self'"]);
    assert.deepEqual(prod["connect-src"], ["'self'"]);
    assert.deepEqual(prod["default-src"], ["'self'"]);
  });

  it("refuses a nonce that is not 16 random bytes", () => {
    assert.throws(() => contentSecurityPolicy("abc"));
    assert.throws(() => contentSecurityPolicy("x' 'unsafe-inline"));
  });
});

describe("proxy.ts", () => {
  const source = readFileSync(new URL("../proxy.ts", import.meta.url), "utf8");

  it("sets the policy on both the request (for Next) and the response (for the browser)", () => {
    assert.match(source, /headers\.set\("Content-Security-Policy", policy\)/);
    assert.match(source, /response\.headers\.set\("Content-Security-Policy", policy\)/);
  });

  it("runs on pages but not on the proxied API or static assets", () => {
    assert.match(source, /\(\?!api\/\|_next\/static\|_next\/image/);
  });

  it("mints a fresh nonce per request", () => {
    assert.match(source, /const nonce = newNonce\(\);/);
  });
});

describe("app/layout.tsx", () => {
  const layout = readFileSync(new URL("../app/layout.tsx", import.meta.url), "utf8");

  it("renders every page per request, which a nonce requires", () => {
    // A prerendered shell is built before any nonce exists; its scripts would
    // carry none and the policy would block them.
    assert.match(layout, /export const instant = false;/);
    assert.match(layout, /await connection\(\);/);
  });
});
