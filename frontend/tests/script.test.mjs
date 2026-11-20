import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { scriptOfWord, scriptRuns } from "../lib/script.ts";

describe("scriptRuns", () => {
  it("splits a Tamil line with English words into script runs", () => {
    const runs = scriptRuns("Samba season-ல மழையால பயிர் சேதமாச்சு crop insurance claim போட்டிருக்கேன்");
    assert.deepEqual(
      runs.map((r) => r.script),
      ["Latn", "Taml", "Latn", "Taml"],
    );
    assert.equal(runs[2].text, "crop insurance claim");
  });

  it("treats romanised Hindi as Latin: script, not language", () => {
    assert.equal(scriptOfWord("namaste"), "Latn");
    assert.equal(scriptOfWord("नमस्ते"), "Deva");
  });

  it("keeps digits inside the run they sit in", () => {
    const runs = scriptRuns("பாலிசி 2026 எண்");
    assert.equal(runs.length, 1);
    assert.equal(runs[0].words, 2);
  });
});
