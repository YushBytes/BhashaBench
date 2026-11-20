import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  CONDITION_KEYS,
  SCENARIO_NOISE_PROFILES,
  SPEAKING_STYLES,
  SWITCH_TRIGGERS,
  draftFromSpec,
  emptyDraft,
  sectionOf,
  slugify,
  specFromDraft,
} from "../lib/scenario-draft.ts";

const SPEC = readFileSync(new URL("../../backend/app/schemas/scenario_spec.py", import.meta.url), "utf8").replaceAll("\r\n", "\n");

/** The string values of one StrEnum class in scenario_spec.py, in order. */
function enumValues(className) {
  const start = SPEC.indexOf(`class ${className}(StrEnum):`);
  assert.ok(start >= 0, `class ${className} not found`);
  const end = SPEC.indexOf("\n\n\nclass ", start);
  const block = SPEC.slice(start, end < 0 ? undefined : end);
  return [...block.matchAll(/^ {4}[A-Z_]+ = "([a-z_]+)"/gm)].map((m) => m[1]);
}

describe("scenario draft", () => {
  it("offers exactly the schema's enumerations", () => {
    assert.deepEqual([...SPEAKING_STYLES], enumValues("SpeakingStyle"));
    assert.deepEqual(SCENARIO_NOISE_PROFILES.map(([v]) => v), enumValues("NoiseProfile"));
    assert.deepEqual(SWITCH_TRIGGERS.map(([v]) => v), enumValues("SwitchTrigger"));
    for (const key of CONDITION_KEYS) assert.ok(SPEC.includes(`\n    ${key}: `), key);
  });

  it("round-trips a full specification without inventing fields", () => {
    const spec = {
      name: "tamil_crop_insurance",
      description: "A farmer checks a claim.",
      language: "ta-IN",
      tags: ["insurance", "demo"],
      persona: { identity: "farmer", speaking_style: "elderly", traits: ["speaks slowly"], accent: "ta-IN.west" },
      goal: { objective: "Check the claim.", max_turns: 16 },
      known_facts: { policy_number: "PMFBY2026114827" },
      expected_outcomes: ["State the claim status"],
      audio: { noise_profile: "rural", snr_db: 10, packet_loss_percent: 8, codec: "g711_alaw", jitter_ms: 40 },
      constraints: { max_silence_seconds: 4, allow_interruptions: true, required_phrases: ["policy number"] },
      code_mixing: {
        primary: "ta-IN",
        secondary: ["en-IN"],
        expected: true,
        switch_triggers: ["numbers"],
        secondary_ratio: 0.35,
        sample_utterances: ["Claim amount evlo varum?"],
      },
    };
    assert.deepEqual(specFromDraft(draftFromSpec(spec)), spec);
  });

  it("omits optional blocks the author left empty", () => {
    const draft = emptyDraft("hi-IN");
    draft.name = "x";
    draft.persona.identity = "caller";
    draft.goal.objective = "Do it.";
    draft.expected_outcomes = ["Done", "  "];
    const spec = specFromDraft(draft);
    assert.equal("constraints" in spec, false);
    assert.equal("code_mixing" in spec, false);
    assert.equal("known_facts" in spec, false);
    assert.deepEqual(spec.expected_outcomes, ["Done"]);
  });

  it("passes unparseable numbers through so the server names the problem", () => {
    const draft = emptyDraft();
    draft.audio.snr_db = "loud";
    assert.equal(specFromDraft(draft).audio.snr_db, "loud");
  });

  it("routes validator errors to the section that owns the field", () => {
    assert.equal(sectionOf("persona.identity"), "caller");
    assert.equal(sectionOf("persona.accent"), "language");
    assert.equal(sectionOf("code_mixing.secondary.0"), "language");
    assert.equal(sectionOf("expected_outcomes"), "goal");
    assert.equal(sectionOf("audio.jitter_ms"), "audio");
    assert.equal(sectionOf("constraints.max_silence_seconds"), "rules");
    assert.equal(sectionOf("name"), "basics");
  });

  it("suggests a name the schema accepts", () => {
    assert.equal(slugify("Crop Insurance — Rural Line!"), "crop_insurance_rural_line");
  });
});
