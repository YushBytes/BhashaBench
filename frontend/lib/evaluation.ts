/**
 * The measured metrics of one evaluation, as rows a page can render.
 *
 * The evaluator stores `metrics` as loose JSON (`EvaluationRead.metrics`).
 * Each metric is either measured, with its value and the basis for it, or
 * not, with the evaluator's own reason. A missing value is rendered
 * "not reported" with that reason. It never becomes 0%, which would read
 * as a perfect transcript or an instant bot.
 */

/** One decimal place, as `formatErrorRate` in format.ts; kept local so this
 *  module has no runtime import and node's test runner can load it as is. */
function formatErrorRate(value: number | null): string | null {
  return value === null ? null : `${(value * 100).toFixed(1)}%`;
}

export interface MetricRow {
  key: string;
  label: string;
  /** Formatted value, or null when the metric was not measured. */
  value: string | null;
  /** What the value rests on, or why there is none. */
  detail: string;
}

type Json = Record<string, unknown>;

const num = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const obj = (value: unknown): Json =>
  value !== null && typeof value === "object" ? (value as Json) : {};

const reasonOf = (metric: Json): string =>
  typeof metric.reason === "string" ? metric.reason : "not reported by the evaluator";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function errorRate(key: string, label: string, metric: Json): MetricRow {
  const value = formatErrorRate(num(metric.value));
  const scored = num(metric.scored_turns) ?? 0;
  return {
    key,
    label,
    value,
    detail:
      value === null
        ? reasonOf(metric)
        : `${plural(scored, "bot turn")} scored against a reviewed reference, ` +
          `${num(metric.errors) ?? 0} errors in ${num(metric.reference_length) ?? 0}`,
  };
}

export function metricRows(metrics: Json): MetricRow[] {
  const rows: MetricRow[] = [];
  if ("wer" in metrics) rows.push(errorRate("wer", "Word error rate", obj(metrics.wer)));
  if ("cer" in metrics) rows.push(errorRate("cer", "Character error rate", obj(metrics.cer)));

  if ("bot_response_latency_ms" in metrics) {
    const metric = obj(metrics.bot_response_latency_ms);
    const p50 = num(metric.p50);
    const p90 = num(metric.p90);
    rows.push({
      key: "latency",
      label: "Bot response latency",
      value: p50 === null ? null : `p50 ${Math.round(p50)} ms · p90 ${Math.round(p90 ?? p50)} ms`,
      detail:
        p50 === null
          ? reasonOf(metric)
          : `${plural(num(metric.samples) ?? 0, "bot turn")} with a measured latency`,
    });
  }

  if ("transcription_failure_rate" in metrics) {
    const metric = obj(metrics.transcription_failure_rate);
    const value = formatErrorRate(num(metric.value));
    rows.push({
      key: "transcription_failure_rate",
      label: "Transcription failures (ours)",
      value,
      detail:
        value === null
          ? reasonOf(metric)
          : `${num(metric.failed) ?? 0} of ${plural(num(metric.bot_turns) ?? 0, "bot turn")} not transcribed`,
    });
  }

  if ("expected_outcome_keyword_coverage" in metrics) {
    const metric = obj(metrics.expected_outcome_keyword_coverage);
    const value = num(metric.value);
    rows.push({
      key: "keyword_coverage",
      label: "Expected-outcome keywords",
      value: value === null ? null : `${Math.round(value * 100)}%`,
      detail:
        value === null
          ? reasonOf(metric)
          : `${num(metric.covered) ?? 0} of ${num(metric.declared) ?? 0} outcomes' keywords heard. ` +
            "A keyword indicator, not a judgement that the outcome happened.",
    });
  }
  return rows;
}
