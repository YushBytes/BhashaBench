/**
 * Per-run channel conditions: the operator overrides `POST /test-runs`
 * accepts as `audio_conditions` (Phase 7). Transcribed from
 * `AudioConditions` in backend/app/schemas/scenario_spec.py, bounds
 * included; `tests/conditions.test.mjs` reads that class and fails if a
 * field or bound here disagrees.
 *
 * An empty field means "not declared": the scenario's own value, if any,
 * applies, and nothing is sent. That is different from zero - 0 ms of
 * jitter is a declared condition. The server validates again and its
 * message is shown as worded.
 */

export type ConditionKey =
  | "gain_db"
  | "clip_threshold"
  | "jitter_ms"
  | "dropout_count"
  | "dropout_ms"
  | "truncate_after_seconds"
  | "leading_silence_ms"
  | "trailing_silence_ms";

export interface NumericCondition {
  key: ConditionKey;
  label: string;
  unit: string;
  min: number;
  max: number;
  integer?: boolean;
  hint: string;
}

export const NUMERIC_CONDITIONS: readonly NumericCondition[] = [
  { key: "gain_db", label: "Gain", unit: "dB", min: -40, max: 0, hint: "Negative is quieter: a soft-spoken caller." },
  { key: "clip_threshold", label: "Clip at", unit: "of full scale", min: 0.05, max: 1, hint: "An overdriven microphone." },
  { key: "jitter_ms", label: "Jitter", unit: "ms", min: 0, max: 300, hint: "Largest per-packet delay; under-runs become silence." },
  { key: "dropout_count", label: "Dropouts", unit: "count", min: 0, max: 20, integer: true, hint: "Silent dead spots in each utterance." },
  { key: "dropout_ms", label: "Dropout length", unit: "ms", min: 20, max: 2000, hint: "Length of each dead spot. Server default 200." },
  { key: "truncate_after_seconds", label: "Truncate after", unit: "s", min: 0.5, max: 600, hint: "Cut the utterance here: a dropped call." },
  { key: "leading_silence_ms", label: "Leading silence", unit: "ms", min: 0, max: 5000, hint: "Silence before the caller speaks." },
  { key: "trailing_silence_ms", label: "Trailing silence", unit: "ms", min: 0, max: 5000, hint: "Silence after the caller speaks." },
];

export const CODECS = [
  ["g711_alaw", "G.711 A-law (India, Europe)"],
  ["g711_ulaw", "G.711 µ-law (North America, Japan)"],
] as const;

export const SAMPLE_RATES_HZ = [8000, 16000, 22050, 24000, 32000, 44100, 48000] as const;

export interface ConditionDraft {
  codec: string;
  sample_rate_hz: string;
  numbers: Partial<Record<ConditionKey, string>>;
}

export type AudioConditionsBody = Partial<Record<ConditionKey, number>> & {
  codec?: string;
  sample_rate_hz?: number;
};

/**
 * The `audio_conditions` body for a draft, or the first problem with it.
 * `body` is null when nothing is declared, so the field is omitted.
 */
export function buildAudioConditions(draft: ConditionDraft): {
  body: AudioConditionsBody | null;
  problem: string | null;
} {
  const body: AudioConditionsBody = {};
  for (const field of NUMERIC_CONDITIONS) {
    const raw = (draft.numbers[field.key] ?? "").trim();
    if (raw === "") continue;
    const value = Number(raw);
    if (!Number.isFinite(value)) return { body: null, problem: `${field.label} is not a number.` };
    if (field.integer && !Number.isInteger(value)) {
      return { body: null, problem: `${field.label} must be a whole number.` };
    }
    if (value < field.min || value > field.max) {
      return {
        body: null,
        problem: `${field.label} must be between ${field.min} and ${field.max} ${field.unit}.`,
      };
    }
    body[field.key] = value;
  }
  if (draft.codec) body.codec = draft.codec;
  if (draft.sample_rate_hz) {
    const rate = Number(draft.sample_rate_hz);
    if (draft.codec && rate !== 8000) {
      return { body: null, problem: "A G.711 codec runs at 8000 Hz; choose 8000 Hz or no rate." };
    }
    body.sample_rate_hz = rate;
  }
  return { body: Object.keys(body).length > 0 ? body : null, problem: null };
}
