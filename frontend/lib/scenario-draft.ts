/**
 * The scenario builder's form state, and its conversion to and from a
 * scenario specification (backend/app/schemas/scenario_spec.py).
 *
 * The form never invents a field: `specFromDraft` emits only keys the schema
 * declares, and omits an optional block the author left empty rather than
 * sending defaults the author did not choose - so a saved scenario says what
 * its author meant, and the server's own defaults apply to the rest. The
 * server validates everything again; this module only shapes the document.
 *
 * Kept free of runtime imports so node's test runner loads it directly.
 */

export const SPEAKING_STYLES = ["polite", "neutral", "brusque", "confused", "hurried", "elderly"] as const;

/** Scenario-level acoustic environments (`NoiseProfile` in scenario_spec.py). */
export const SCENARIO_NOISE_PROFILES = [
  ["clean", "Clean"],
  ["urban", "Urban street"],
  ["rural", "Rural"],
  ["market", "Market"],
  ["indoor_fan", "Indoor, fan running"],
  ["worst_case", "Worst case"],
] as const;

export const SWITCH_TRIGGERS = [
  ["numbers", "Numbers, amounts and dates"],
  ["technical_terms", "Technical terms"],
  ["proper_nouns", "Names of people, places, brands"],
  ["frustration", "Frustration with the bot"],
  ["clarification", "Repeating a misheard phrase"],
  ["throughout", "Habitual mixing throughout"],
] as const;

export const CONDITION_KEYS = [
  "gain_db",
  "clip_threshold",
  "jitter_ms",
  "dropout_count",
  "dropout_ms",
  "truncate_after_seconds",
  "leading_silence_ms",
  "trailing_silence_ms",
] as const;

export type ConditionField = (typeof CONDITION_KEYS)[number];

export interface Draft {
  name: string;
  description: string;
  language: string;
  tags: string[];
  persona: { identity: string; speaking_style: string; traits: string[]; accent: string };
  goal: { objective: string; max_turns: string };
  known_facts: { key: string; value: string }[];
  expected_outcomes: string[];
  audio: {
    noise_profile: string;
    snr_db: string;
    packet_loss_percent: string;
    codec: string;
    sample_rate_hz: string;
    conditions: Partial<Record<ConditionField, string>>;
  };
  constraints: {
    enabled: boolean;
    max_silence_seconds: string;
    allow_interruptions: boolean;
    required_phrases: string[];
    forbidden_phrases: string[];
  };
  code_mixing: {
    enabled: boolean;
    secondary: string[];
    expected: boolean;
    switch_triggers: string[];
    secondary_ratio: string;
    sample_utterances: string[];
  };
}

export function emptyDraft(language = "hi-IN"): Draft {
  return {
    name: "",
    description: "",
    language,
    tags: [],
    persona: { identity: "", speaking_style: "neutral", traits: [], accent: "" },
    goal: { objective: "", max_turns: "20" },
    known_facts: [],
    expected_outcomes: [""],
    audio: { noise_profile: "clean", snr_db: "30", packet_loss_percent: "0", codec: "", sample_rate_hz: "", conditions: {} },
    constraints: {
      enabled: false,
      max_silence_seconds: "5",
      allow_interruptions: true,
      required_phrases: [],
      forbidden_phrases: [],
    },
    code_mixing: {
      enabled: false,
      secondary: [],
      expected: true,
      switch_triggers: [],
      secondary_ratio: "",
      sample_utterances: [],
    },
  };
}

type Json = Record<string, unknown>;
const obj = (v: unknown): Json => (v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Json) : {});
const str = (v: unknown): string => (v === null || v === undefined ? "" : String(v));
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.map(str) : []);

/** Fill a draft from a stored or parsed specification. Unknown keys are dropped. */
export function draftFromSpec(spec: unknown): Draft {
  const s = obj(spec);
  const persona = obj(s.persona);
  const goal = obj(s.goal);
  const audio = obj(s.audio);
  const constraints = s.constraints ? obj(s.constraints) : null;
  const mixing = s.code_mixing ? obj(s.code_mixing) : null;
  const base = emptyDraft(str(s.language) || "hi-IN");
  const conditions: Partial<Record<ConditionField, string>> = {};
  for (const key of CONDITION_KEYS) if (audio[key] !== undefined && audio[key] !== null) conditions[key] = str(audio[key]);
  const outcomes = strs(s.expected_outcomes);
  return {
    ...base,
    name: str(s.name),
    description: str(s.description),
    tags: strs(s.tags),
    persona: {
      identity: str(persona.identity),
      speaking_style: str(persona.speaking_style) || "neutral",
      traits: strs(persona.traits),
      accent: str(persona.accent),
    },
    goal: { objective: str(goal.objective), max_turns: goal.max_turns === undefined ? "20" : str(goal.max_turns) },
    known_facts: Object.entries(obj(s.known_facts)).map(([key, value]) => ({ key, value: str(value) })),
    expected_outcomes: outcomes.length > 0 ? outcomes : [""],
    audio: {
      noise_profile: str(audio.noise_profile) || "clean",
      snr_db: audio.snr_db === undefined ? "30" : str(audio.snr_db),
      packet_loss_percent: audio.packet_loss_percent === undefined ? "0" : str(audio.packet_loss_percent),
      codec: str(audio.codec),
      sample_rate_hz: str(audio.sample_rate_hz),
      conditions,
    },
    constraints: constraints
      ? {
          enabled: true,
          max_silence_seconds: constraints.max_silence_seconds === undefined ? "5" : str(constraints.max_silence_seconds),
          allow_interruptions: constraints.allow_interruptions !== false,
          required_phrases: strs(constraints.required_phrases),
          forbidden_phrases: strs(constraints.forbidden_phrases),
        }
      : base.constraints,
    code_mixing: mixing
      ? {
          enabled: true,
          secondary: strs(mixing.secondary),
          expected: mixing.expected !== false,
          switch_triggers: strs(mixing.switch_triggers),
          secondary_ratio: mixing.secondary_ratio === undefined || mixing.secondary_ratio === null ? "" : str(mixing.secondary_ratio),
          sample_utterances: strs(mixing.sample_utterances),
        }
      : base.code_mixing,
  };
}

/** A number the author typed, or the raw text so the server can name the problem. */
function numeric(value: string): number | string {
  const trimmed = value.trim();
  const n = Number(trimmed);
  return trimmed !== "" && Number.isFinite(n) ? n : trimmed;
}

const clean = (list: string[]) => list.map((item) => item.trim()).filter(Boolean);

/** The specification for a draft, omitting what the author left empty. */
export function specFromDraft(d: Draft): Json {
  const spec: Json = { name: d.name.trim(), language: d.language };
  if (d.description.trim()) spec.description = d.description.trim();
  const tags = clean(d.tags);
  if (tags.length > 0) spec.tags = tags;

  const persona: Json = { identity: d.persona.identity.trim(), speaking_style: d.persona.speaking_style };
  const traits = clean(d.persona.traits);
  if (traits.length > 0) persona.traits = traits;
  if (d.persona.accent) persona.accent = d.persona.accent;
  spec.persona = persona;

  spec.goal = { objective: d.goal.objective.trim(), max_turns: numeric(d.goal.max_turns || "20") };

  const facts = d.known_facts.filter((f) => f.key.trim() || f.value.trim());
  if (facts.length > 0) spec.known_facts = Object.fromEntries(facts.map((f) => [f.key.trim(), f.value.trim()]));

  spec.expected_outcomes = clean(d.expected_outcomes);

  const audio: Json = {
    noise_profile: d.audio.noise_profile,
    snr_db: numeric(d.audio.snr_db || "30"),
    packet_loss_percent: numeric(d.audio.packet_loss_percent || "0"),
  };
  if (d.audio.codec) audio.codec = d.audio.codec;
  if (d.audio.sample_rate_hz) audio.sample_rate_hz = numeric(d.audio.sample_rate_hz);
  for (const key of CONDITION_KEYS) {
    const raw = (d.audio.conditions[key] ?? "").trim();
    if (raw !== "") audio[key] = numeric(raw);
  }
  spec.audio = audio;

  if (d.constraints.enabled) {
    const c: Json = {
      max_silence_seconds: numeric(d.constraints.max_silence_seconds || "5"),
      allow_interruptions: d.constraints.allow_interruptions,
    };
    const required = clean(d.constraints.required_phrases);
    const forbidden = clean(d.constraints.forbidden_phrases);
    if (required.length > 0) c.required_phrases = required;
    if (forbidden.length > 0) c.forbidden_phrases = forbidden;
    spec.constraints = c;
  }

  if (d.code_mixing.enabled) {
    const m: Json = { primary: d.language, secondary: d.code_mixing.secondary, expected: d.code_mixing.expected };
    if (d.code_mixing.switch_triggers.length > 0) m.switch_triggers = d.code_mixing.switch_triggers;
    if (d.code_mixing.secondary_ratio.trim() !== "") m.secondary_ratio = numeric(d.code_mixing.secondary_ratio);
    const samples = clean(d.code_mixing.sample_utterances);
    if (samples.length > 0) m.sample_utterances = samples;
    spec.code_mixing = m;
  }
  return spec;
}

export type SectionId = "basics" | "caller" | "goal" | "language" | "audio" | "rules";

/** Which builder section owns a validator error's field path. */
export function sectionOf(field: string): SectionId {
  const head = field.split(/[.[]/)[0];
  if (head === "persona") return field.startsWith("persona.accent") ? "language" : "caller";
  if (head === "goal" || head === "expected_outcomes" || head === "known_facts") return "goal";
  if (head === "code_mixing" || head === "language") return "language";
  if (head === "audio") return "audio";
  if (head === "constraints") return "rules";
  return "basics";
}

/** Machine-friendly names: what `ScenarioName` accepts. */
export const NAME_PATTERN = /^[a-z0-9][a-z0-9_-]*$/;

/** Suggest a valid name from free text. */
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 200);
}
