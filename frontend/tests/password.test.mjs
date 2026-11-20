import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { MAX_PASSWORD_CHARS, MIN_PASSWORD_CHARS, passwordProblem } from "../lib/password.ts";

const SOURCE = readFileSync(new URL("../../backend/app/auth/passwords.py", import.meta.url), "utf8");

describe("passwordProblem", () => {
  it("uses the server's bounds", () => {
    assert.equal(Number(/MIN_PASSWORD_CHARS = (\d+)/.exec(SOURCE)?.[1]), MIN_PASSWORD_CHARS);
    assert.equal(Number(/MAX_PASSWORD_CHARS = (\d+)/.exec(SOURCE)?.[1]), MAX_PASSWORD_CHARS);
  });

  it("refuses short, blank and email-as-password, and accepts a long phrase", () => {
    assert.match(passwordProblem("short"), /at least 12/);
    assert.match(passwordProblem(" ".repeat(14)), /only spaces/);
    assert.match(passwordProblem("Me@Example.test", "me@example.test"), /email/);
    assert.equal(passwordProblem("a long enough phrase"), null);
  });
});
