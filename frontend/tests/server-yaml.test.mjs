// The builder's YAML must mean the same thing to PyYAML (YAML 1.1).

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { toServerYaml } from "../lib/server-yaml.ts";

describe("toServerYaml", () => {
  it("quotes strings YAML 1.1 would read as dates, booleans or numbers", () => {
    const out = toServerYaml({ known_facts: { incident_date: "2026-10-28", consent: "yes", flag: "on", last_four: "0083" } });
    assert.match(out, /incident_date"?: "2026-10-28"/);
    assert.match(out, /consent"?: "yes"/);
    assert.match(out, /flag"?: "on"/);
    assert.match(out, /last_four"?: "0083"/);
  });

  it("leaves real numbers and booleans as they are", () => {
    const out = toServerYaml({ max_turns: 20, enabled: true });
    assert.match(out, /max_turns"?: 20\b/);
    assert.match(out, /enabled"?: true\b/);
  });
});
