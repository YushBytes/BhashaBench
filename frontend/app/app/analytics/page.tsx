import Link from "next/link";
import { Suspense } from "react";

import { PageBody, PageHeader } from "@/components/shell/page-header";
import { TableSkeleton } from "@/components/ui/loading";
import {
  EmptyState,
  ErrorState,
  Fact,
  NotReported,
  Panel,
  PanelHeader,
  TableScroll,
  Td,
  Th,
  buttonClass,
  cx,
} from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import { sessionHeaders, signInAgainIfExpired } from "@/lib/api/server";
import type {
  AnalyticsDimension,
  AnalyticsSummary,
  AnalyticsTrend,
  Page,
  RegressionResult,
  RunSummary,
  VerdictTally,
} from "@/lib/api/types";
import {
  formatErrorRate,
  formatMs,
  formatPassRate,
  formatTimestampShort,
  humanise,
  shortId,
} from "@/lib/format";

export const metadata = { title: "Analytics" };

type SearchParams = Record<string, string | string[] | undefined>;

const DIMENSIONS: { value: AnalyticsDimension; label: string }[] = [
  { value: "language", label: "Language" },
  { value: "scenario_name", label: "Scenario" },
  { value: "bot_adapter", label: "Bot adapter" },
  { value: "mode", label: "Mode" },
  { value: "outcome", label: "Outcome" },
];

function one(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value || undefined;
}

export default function AnalyticsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return (
    <>
      <PageHeader
        title="Analytics"
        description="Computed from your stored runs and each run's latest evaluation - nothing sampled, nothing estimated. A pass rate counts decided runs only and always carries its interval and n."
      />
      <PageBody>
        <Suspense fallback={<TableSkeleton />}>
          <Analytics searchParams={searchParams} />
        </Suspense>
      </PageBody>
    </>
  );
}

function PassRate({ tally }: { tally: VerdictTally }) {
  const text = formatPassRate(tally.pass_rate);
  return text === null ? (
    <span className="text-text-dim">No decided runs</span>
  ) : (
    <span className="font-mono tabular-nums">{text}</span>
  );
}

function Verdicts({ tally }: { tally: VerdictTally }) {
  const v = tally.verdicts;
  return (
    <span className="font-mono text-[13px] tabular-nums text-text-muted">
      {v.pass} pass · {v.fail} fail · {v.undetermined} undetermined · {v.not_evaluated} not evaluated
    </span>
  );
}

async function Analytics({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const auth = await sessionHeaders();
  const params = await searchParams;
  const requested = one(params.group_by);
  const groupBy = DIMENSIONS.some((d) => d.value === requested)
    ? (requested as AnalyticsDimension)
    : "language";
  const regressionQuery = {
    baseline_created_after: one(params.baseline_created_after),
    baseline_created_before: one(params.baseline_created_before),
    candidate_created_after: one(params.candidate_created_after),
    candidate_created_before: one(params.candidate_created_before),
  };
  const wantsRegression = Object.values(regressionQuery).some(Boolean);

  let summary: AnalyticsSummary;
  let trend: AnalyticsTrend;
  let regression: RegressionResult | null = null;
  let finished: RunSummary[] | null = null;
  try {
    let recent: Page<RunSummary> | null;
    [summary, trend, regression, recent] = await Promise.all([
      api.analyticsSummary({ cache: "no-store", headers: auth, query: { group_by: groupBy } }),
      api.analyticsTrend({ cache: "no-store", headers: auth, query: { bucket: "day" } }),
      wantsRegression
        ? api.regressions({ cache: "no-store", headers: auth, query: regressionQuery })
        : Promise.resolve(null),
      // For the comparison pickers; without it the form falls back to ids.
      api
        .runs({ cache: "no-store", headers: auth, query: { status: "completed", limit: 100 } })
        .catch(() => null),
    ]);
    finished = recent?.items ?? null;
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState
          title="Analytics could not be loaded"
          detail={error instanceof ApiError ? error.message : "The analytics request failed."}
        />
      </Panel>
    );
  }

  if (summary.overall.runs === 0) {
    return (
      <Panel>
        <EmptyState
          title="No runs to analyse yet"
          action={
            <Link href="/app/new-test" className={buttonClass("primary", "sm")}>
              Configure a run
            </Link>
          }
        >
          These views fill from runs you have executed and evaluated. There is no sample data.
        </EmptyState>
      </Panel>
    );
  }

  const latency = summary.metrics.per_run_median_latency_ms;
  const wer = summary.metrics.wer_pooled;

  return (
    <div className="grid min-w-0 gap-5">
      {summary.warnings.length > 0 ? (
        <Panel className="border-warn/40 p-4">
          {summary.warnings.map((warning) => (
            <p key={warning} role="note" className="text-[13px] text-text">
              {warning}
            </p>
          ))}
        </Panel>
      ) : null}

      <Panel>
        <PanelHeader title="Overall" description="Each run counted once, by its latest evaluation." />
        <dl className="grid gap-4 p-4 sm:grid-cols-2 sm:p-5 xl:grid-cols-4">
          <Fact label="Pass rate (Wilson 95%)">
            <PassRate tally={summary.overall} />
          </Fact>
          <Fact label="Runs">
            <Verdicts tally={summary.overall} />
          </Fact>
          <Fact label="Word error rate (pooled)" hint="Total errors over total reference words">
            {wer.value === null ? (
              <NotReported what="no reviewed reference transcripts yet" />
            ) : (
              <span className="font-mono tabular-nums">
                {formatErrorRate(wer.value)} · {wer.reference_words} words, {wer.runs_with_references} runs
              </span>
            )}
          </Fact>
          <Fact label="Bot latency, per-run median" hint={latency.note}>
            {latency.runs === 0 ? (
              <NotReported what="no run measured latency" />
            ) : (
              <span className="font-mono tabular-nums">
                p50 {formatMs(latency.p50)} · p90 {formatMs(latency.p90)} · {latency.runs} runs
              </span>
            )}
          </Fact>
        </dl>
      </Panel>

      <Panel>
        <PanelHeader
          title="By group"
          actions={
            <nav aria-label="Group by" className="flex flex-wrap gap-1">
              {DIMENSIONS.map((d) => (
                <Link
                  key={d.value}
                  href={`/app/analytics?group_by=${d.value}`}
                  aria-current={d.value === groupBy ? "page" : undefined}
                  className={cx(buttonClass(d.value === groupBy ? "primary" : "default", "sm"))}
                >
                  {d.label}
                </Link>
              ))}
            </nav>
          }
        />
        <TableScroll>
          <table className="w-full min-w-max text-left text-[13px]">
            <thead>
              <tr>
                <Th>{DIMENSIONS.find((d) => d.value === groupBy)?.label}</Th>
                <Th>Runs</Th>
                <Th>Pass rate (95% interval, n)</Th>
                <Th>Verdicts</Th>
              </tr>
            </thead>
            <tbody>
              {summary.groups.map((group) => (
                <tr key={String(group.key)} className="border-t border-line">
                  <Td className="font-medium text-text">{group.key ?? <span className="text-text-dim">not recorded</span>}</Td>
                  <Td className="font-mono tabular-nums">{group.runs}</Td>
                  <Td><PassRate tally={group} /></Td>
                  <Td><Verdicts tally={group} /></Td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      </Panel>

      <Panel>
        <PanelHeader title="By day" description="Runs grouped by the day they were created (UTC)." />
        <TableScroll>
          <table className="w-full min-w-max text-left text-[13px]">
            <thead>
              <tr>
                <Th>Day</Th>
                <Th>Runs</Th>
                <Th>Pass rate (95% interval, n)</Th>
              </tr>
            </thead>
            <tbody>
              {trend.periods.map((period) => (
                <tr key={period.period} className="border-t border-line">
                  <Td className="font-mono">{period.period.slice(0, 10)}</Td>
                  <Td className="font-mono tabular-nums">{period.runs}</Td>
                  <Td><PassRate tally={period} /></Td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      </Panel>

      <div className="grid min-w-0 gap-5 xl:grid-cols-2">
        <Panel>
          <PanelHeader
            title="Compare two runs"
            description="Verdict and metric deltas between two evaluated runs. Two single runs support no statistical claim."
          />
          <form action="/app/compare" method="get" className="grid gap-3 p-4 sm:p-5">
            {finished && finished.length >= 2 ? (
              <>
                <RunPicker name="baseline" label="Baseline" runs={finished} preselect={1} />
                <RunPicker name="candidate" label="Candidate" runs={finished} preselect={0} />
                <p className="text-[12px] leading-relaxed text-text-muted">
                  The {finished.length} most recent completed runs. Both must have been
                  evaluated; the comparison says so if one has not.
                </p>
              </>
            ) : (
              <>
                <RunIdField name="baseline" label="Baseline run id" />
                <RunIdField name="candidate" label="Candidate run id" />
              </>
            )}
            <button type="submit" className={buttonClass("primary", "sm", "justify-self-start")}>
              Compare
            </button>
          </form>
        </Panel>

        <Panel>
          <PanelHeader
            title="Regression check"
            description="Pass rate of runs created in one period against another, by Fisher's exact test. Called a regression only at p < 0.05 with at least five decided runs a side."
          />
          <form action="/app/analytics" method="get" className="grid gap-3 p-4 sm:grid-cols-2 sm:p-5">
            <input type="hidden" name="group_by" value={groupBy} />
            <DateField name="baseline_created_after" label="Baseline from" value={regressionQuery.baseline_created_after} />
            <DateField name="baseline_created_before" label="Baseline before" value={regressionQuery.baseline_created_before} />
            <DateField name="candidate_created_after" label="Candidate from" value={regressionQuery.candidate_created_after} />
            <DateField name="candidate_created_before" label="Candidate before" value={regressionQuery.candidate_created_before} />
            <button type="submit" className={buttonClass("primary", "sm", "justify-self-start")}>
              Check
            </button>
          </form>
          {regression !== null ? <RegressionVerdict result={regression} /> : null}
        </Panel>
      </div>
    </div>
  );
}

function RunPicker({
  name,
  label,
  runs,
  preselect,
}: {
  name: string;
  label: string;
  runs: RunSummary[];
  /** Index into `runs` (newest first): the candidate defaults to the newest,
   *  the baseline to the one before it. */
  preselect: number;
}) {
  return (
    <label className="block text-[13px] font-medium text-text-muted">
      {label}
      <select
        name={name}
        required
        defaultValue={runs[preselect]?.run_id}
        className="mt-1.5 block w-full rounded-md border border-line-strong bg-surface-raised px-3 py-2 text-[13px] text-text"
      >
        {runs.map((run) => (
          <option key={run.run_id} value={run.run_id}>
            {[
              run.scenario_name,
              humanise(run.mode),
              run.noise_profile ? humanise(run.noise_profile) : null,
              formatTimestampShort(run.created_at),
              shortId(run.run_id),
            ]
              .filter(Boolean)
              .join(" · ")}
          </option>
        ))}
      </select>
    </label>
  );
}

function RunIdField({ name, label }: { name: string; label: string }) {
  return (
    <label className="block text-[13px] font-medium text-text-muted">
      {label}
      <input
        name={name}
        required
        pattern="[0-9a-fA-F-]{36}"
        placeholder="00000000-0000-0000-0000-000000000000"
        className="mt-1.5 block w-full rounded-md border border-line-strong bg-surface-raised px-3 py-2 font-mono text-[13px] text-text"
      />
    </label>
  );
}

function DateField({ name, label, value }: { name: string; label: string; value?: string }) {
  return (
    <label className="block text-[13px] font-medium text-text-muted">
      {label}
      <input
        type="date"
        name={name}
        defaultValue={value}
        className="mt-1.5 block w-full rounded-md border border-line-strong bg-surface-raised px-3 py-2 text-[13px] text-text"
      />
    </label>
  );
}

function RegressionVerdict({ result }: { result: RegressionResult }) {
  return (
    <div className="border-t border-line p-4 sm:p-5" role="status">
      <p className="text-[15px] font-semibold text-text">{humanise(result.conclusion)}</p>
      <p className="mt-1 text-[13px] text-text-muted">{result.reason}</p>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2">
        <Fact label="Baseline"><PassRate tally={result.baseline} /></Fact>
        <Fact label="Candidate"><PassRate tally={result.candidate} /></Fact>
        <Fact label="p-value (two-sided)">
          {result.p_value === null ? <NotReported what="a group has no decided runs" /> : (
            <span className="font-mono tabular-nums">{result.p_value.toFixed(4)}</span>
          )}
        </Fact>
      </dl>
      {result.warnings.map((warning) => (
        <p key={warning} className="mt-2 text-[12px] text-warn">{warning}</p>
      ))}
    </div>
  );
}
