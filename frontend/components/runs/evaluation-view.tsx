/**
 * One run's evaluation: the verdict, every criterion with its reason, and
 * every measured metric beside the catalogue's own definition of it
 * (`GET /evaluation/metrics`) - name, value, definition, formula, evidence
 * and limitations.
 *
 * A metric the evaluator could not compute shows its reason and never a
 * number. Qualities that would need the unvalidated language-model judge are
 * listed as unavailable, not scored. There is no composite score; the
 * catalogue says so and so does this view.
 */

import { CheckCircle2, CircleDashed, CircleSlash, XCircle } from "lucide-react";

import { EmptyState, cx } from "@/components/ui/primitives";
import { VerdictBadge } from "@/components/ui/status";
import type { EvaluationRead, MetricCatalogue, MetricDefinition } from "@/lib/api/types";
import { unmeasuredQualities, unmeasuredReason } from "@/lib/content";
import { metricRows } from "@/lib/evaluation";
import { formatTimestamp, humanise } from "@/lib/format";

/** `metricRows` key -> catalogue metric name. */
const CATALOGUE_KEY: Record<string, string> = {
  wer: "wer",
  cer: "cer",
  wer_by_script: "wer_by_script",
  script_mixing: "script_mixing",
  latency: "bot_response_latency_ms",
  transcription_failure_rate: "transcription_failure_rate",
  keyword_coverage: "expected_outcome_keyword_coverage",
};

function CriterionIcon({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === "pass" || s === "passed") return <CheckCircle2 aria-hidden="true" className="size-4 text-ok" />;
  if (s === "fail" || s === "failed") return <XCircle aria-hidden="true" className="size-4 text-bad" />;
  return <CircleDashed aria-hidden="true" className="size-4 text-text-3" />;
}

function Definition({ def }: { def: MetricDefinition | undefined }) {
  if (!def) return null;
  return (
    <details className="group mt-2">
      <summary className="cursor-pointer text-[12px] font-medium text-accent hover:underline">How this is measured</summary>
      <dl className="mt-2 grid gap-2 rounded-md bg-bg-soft p-3 text-[12px] leading-relaxed">
        <div>
          <dt className="font-medium text-text">Definition</dt>
          <dd className="text-text-2">{def.definition}</dd>
        </div>
        <div>
          <dt className="font-medium text-text">Formula</dt>
          <dd className="font-mono text-[11.5px] text-text-2">{def.formula}</dd>
        </div>
        <div>
          <dt className="font-medium text-text">Evidence</dt>
          <dd className="text-text-2">{def.evidence}</dd>
        </div>
        <div>
          <dt className="font-medium text-text">When data is missing</dt>
          <dd className="text-text-2">{def.missing_data}</dd>
        </div>
        {def.limitations.length > 0 ? (
          <div>
            <dt className="font-medium text-text">Limitations</dt>
            <dd>
              <ul className="list-disc space-y-0.5 pl-4 text-text-2">
                {def.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </dd>
          </div>
        ) : null}
      </dl>
    </details>
  );
}

export function EvaluationView({
  evaluations,
  catalogue,
  finished,
}: {
  evaluations: EvaluationRead[];
  catalogue: MetricCatalogue | null;
  finished: boolean;
}) {
  const latest = evaluations[0] ?? null;
  const defs = new Map((catalogue?.metrics ?? []).map((m) => [m.name, m]));

  if (!latest) {
    return (
      <EmptyState title={finished ? "Not evaluated yet" : "Nothing to evaluate yet"}>
        {finished
          ? "Evaluate the run to get a verdict with a reason for every criterion. Evaluating again later appends; history is kept."
          : "The run has not finished. Evaluation reads only what a finished run stored."}
      </EmptyState>
    );
  }

  const rows = metricRows(latest.metrics);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-bg p-4 shadow-1 sm:p-5">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-[13px] text-text-3">Verdict</span>
          <VerdictBadge verdict={latest.verdict} />
        </div>
        <p className="font-mono text-[12px] text-text-3">
          {latest.evaluator_version}
          {catalogue ? ` · ${catalogue.normalisation_version}` : ""} · {formatTimestamp(latest.created_at)}
        </p>
        {!latest.measures_audio ? (
          <p className="basis-full text-[12px] text-text-3">This mode moved no audio, so nothing here describes speech recognition, synthesis or the line.</p>
        ) : null}
      </div>

      <section aria-labelledby="criteria-title" className="space-y-2">
        <h3 id="criteria-title" className="text-[14px] font-semibold text-text">
          Criteria
        </h3>
        <ul className="divide-y divide-line rounded-lg border border-line bg-bg shadow-1">
          {latest.criteria.map((c) => (
            <li key={c.name} className="flex gap-3 px-4 py-3">
              <CriterionIcon status={c.status} />
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-baseline gap-x-2 text-[14px]">
                  <span className="font-medium text-text">{defs.get(c.name)?.title ?? humanise(c.name)}</span>
                  <span className="font-mono text-[12px] text-text-3">{c.status}</span>
                </p>
                <p className="mt-0.5 text-[13px] leading-relaxed text-text-2">{c.reason}</p>
                <Definition def={defs.get(c.name)} />
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="metrics-title" className="space-y-2">
        <h3 id="metrics-title" className="text-[14px] font-semibold text-text">
          Measured metrics
        </h3>
        <p className="text-[12px] text-text-3">No composite score is computed. Each metric stands on its own evidence.</p>
        <ul className="grid gap-3 md:grid-cols-2">
          {rows.map((row) => (
            <li key={row.key} className="min-w-0 rounded-lg border border-line bg-bg p-4 shadow-1">
              <p className="text-[12px] font-medium text-text-3">{row.label}</p>
              {row.value === null ? (
                <p className="mt-1.5 inline-flex items-center gap-1.5 text-[14px] text-text-3">
                  <CircleSlash aria-hidden="true" className="size-4" /> Not reported
                </p>
              ) : (
                <p className={cx("mt-1.5 break-words font-mono font-medium text-text tabular", row.value.length > 22 ? "text-[14px]" : "text-[22px] tracking-[-0.02em]")}>
                  {row.value}
                </p>
              )}
              <p className="mt-1.5 text-[12px] leading-relaxed text-text-2">{row.detail}</p>
              <Definition def={defs.get(CATALOGUE_KEY[row.key] ?? row.key)} />
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="unmeasured-title" className="rounded-lg border border-dashed border-line-strong p-4">
        <h3 id="unmeasured-title" className="text-[14px] font-semibold text-text">
          Not measured
        </h3>
        <ul className="mt-2 flex flex-wrap gap-2">
          {unmeasuredQualities.map((q) => (
            <li key={q} className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-2.5 py-1 text-[12px] text-text-2">
              <CircleSlash aria-hidden="true" className="size-3 text-text-3" />
              {q}
              <span className="sr-only">: unavailable</span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[12px] leading-relaxed text-text-3">{unmeasuredReason}</p>
      </section>

      {evaluations.length > 1 ? (
        <section aria-labelledby="history-title" className="space-y-2">
          <h3 id="history-title" className="text-[14px] font-semibold text-text">
            Earlier evaluations
          </h3>
          <ul className="divide-y divide-line rounded-lg border border-line bg-bg">
            {evaluations.slice(1).map((e) => (
              <li key={e.evaluation_id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-[13px]">
                <VerdictBadge verdict={e.verdict} />
                <span className="font-mono text-[12px] text-text-3">
                  {e.evaluator_version} · {formatTimestamp(e.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
