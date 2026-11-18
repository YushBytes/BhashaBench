// The run history's filter values against the backend enums they are sent
// to. A value the API does not accept is a 422, and the page then shows
// "could not be loaded" instead of a filtered list - which is what the
// "Created" status option did until this test existed.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { RUN_MODES, RUN_OUTCOMES, RUN_STATUSES } from "../lib/run-filters.ts";

const BACKEND = new URL("../../backend/app/", import.meta.url);

/** The string values of `class <name>(StrEnum)` in a backend module. */
function enumValues(module, name) {
  const source = readFileSync(new URL(module, BACKEND), "utf8");
  const start = source.indexOf(`class ${name}(`);
  assert.ok(start >= 0, `class ${name} not found in ${module}`);
  const body = source.slice(start).split(/\nclass |\n[A-Z_]+[:=]|\ndef /)[0];
  return new Set([...body.matchAll(/^\s+[A-Z_]+ = "([a-z_]+)"/gm)].map((m) => m[1]));
}

describe("run filters", () => {
  it("offer only persisted run statuses", () => {
    const allowed = enumValues("models/test_run.py", "RunStatus");
    for (const [value] of RUN_STATUSES) assert.ok(allowed.has(value), `status ${value}`);
    assert.equal(RUN_STATUSES.length, allowed.size, "every persisted status is offered");
  });

  it("offer every creatable execution mode and no other", () => {
    const allowed = enumValues("pipeline/modes.py", "ExecutionMode");
    allowed.delete("telephony_test"); // excluded from IMPLEMENTED_MODES: no run has it
    assert.deepEqual(new Set(RUN_MODES.map(([value]) => value)), allowed);
  });

  it("offer every run outcome and no other", () => {
    const allowed = enumValues("pipeline/modes.py", "RunOutcome");
    assert.deepEqual(new Set(RUN_OUTCOMES.map(([value]) => value)), allowed);
  });
});
