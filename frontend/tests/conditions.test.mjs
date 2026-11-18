// Per-run channel conditions against the backend class they are sent to.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  CODECS,
  NUMERIC_CONDITIONS,
  SAMPLE_RATES_HZ,
  buildAudioConditions,
} from "../lib/conditions.ts";

const SPEC = readFileSync(new URL("../../backend/app/schemas/scenario_spec.py", import.meta.url), "utf8");
const block = SPEC.slice(SPEC.indexOf("class AudioConditions("), SPEC.indexOf("CONDITION_FIELDS"));

/** `name: float | None = Field(default=None, ge=.., le=..)` -> bounds. */
function backendFields() {
  const fields = new Map();
  for (const match of block.matchAll(/^    ([a-z_]+): [^=\n]+= Field\(([\s\S]*?)\n    \)|^    ([a-z_]+): [^=\n]+= Field\(([^\n]*)\)$/gm)) {
    const name = match[1] ?? match[3];
    const args = match[2] ?? match[4];
    const ge = /ge=(-?[\d.]+)/.exec(args);
    const le = /le=(-?[\d.]+)/.exec(args);
    fields.set(name, { min: ge ? Number(ge[1]) : null, max: le ? Number(le[1]) : null });
  }
  return fields;
}

describe("channel conditions", () => {
  const backend = backendFields();

  it("cover every AudioConditions field, with the backend's bounds", () => {
    const ours = new Set([...NUMERIC_CONDITIONS.map((f) => f.key), "codec", "sample_rate_hz"]);
    assert.deepEqual(ours, new Set(backend.keys()));
    for (const field of NUMERIC_CONDITIONS) {
      const theirs = backend.get(field.key);
      assert.deepEqual([field.min, field.max], [theirs.min, theirs.max], field.key);
    }
  });

  it("offer exactly the backend's codecs and sample rates", () => {
    assert.deepEqual(new Set(CODECS.map(([v]) => v)), new Set([...SPEC.matchAll(/G711_[A-Z]+ = "([a-z0-9_]+)"/g)].map((m) => m[1])));
    const rates = /SUPPORTED_SAMPLE_RATES_HZ: frozenset\[int\] = frozenset\(\s*\{([^}]*)\}/.exec(SPEC)[1];
    assert.deepEqual([...SAMPLE_RATES_HZ], rates.split(",").map((r) => Number(r.trim())).sort((a, b) => a - b));
  });

  it("sends nothing when nothing is declared", () => {
    assert.deepEqual(buildAudioConditions({ codec: "", sample_rate_hz: "", numbers: {} }), { body: null, problem: null });
  });

  it("sends a declared zero, which is not the same as undeclared", () => {
    const { body } = buildAudioConditions({ codec: "", sample_rate_hz: "", numbers: { jitter_ms: "0", gain_db: "" } });
    assert.deepEqual(body, { jitter_ms: 0 });
  });

  it("refuses out-of-range values, fractions of a count and a codec at the wrong rate", () => {
    assert.match(buildAudioConditions({ codec: "", sample_rate_hz: "", numbers: { jitter_ms: "301" } }).problem, /between 0 and 300/);
    assert.match(buildAudioConditions({ codec: "", sample_rate_hz: "", numbers: { dropout_count: "2.5" } }).problem, /whole number/);
    assert.match(buildAudioConditions({ codec: "g711_alaw", sample_rate_hz: "16000", numbers: {} }).problem, /8000 Hz/);
    assert.deepEqual(buildAudioConditions({ codec: "g711_alaw", sample_rate_hz: "8000", numbers: {} }).body, { codec: "g711_alaw", sample_rate_hz: 8000 });
  });
});
