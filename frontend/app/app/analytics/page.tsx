import Link from "next/link";
import { Suspense } from "react";
import { AlertTriangle, Download, FlaskConical } from "lucide-react";

import { PassRateIntervals } from "@/components/charts/pass-rate-intervals";
import { VerdictTrend } from "@/components/charts/verdict-trend";
import { PageBody, PageHeader } from "@/components/shell/page";
import { Input, Select } from "@/components/ui/field";
import {
  ButtonLink,
  EmptyState,
  ErrorState,
  Fact,
  NotReported,
  Panel,
  PanelBody,
  PanelHeader,
  Stat,
  StatsSkeleton,
  Table,
  TableScroll,
  Td,
  Th,
  buttonClass,
  cx,
} from "@/components/ui/primitives";
import { ApiError, api, runsCsvUrl } from "@/lib/api/client";
import { loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { AnalyticsDimension, AnalyticsSummary, AnalyticsTrend, BotAdapters, LanguageCatalogue, RegressionResult, SuiteSummary, VerdictTally } from "@/lib/api/types";
import { formatErrorRate, formatMs, formatPassRate, humanise } from "@/lib/format";
import { RUN_MODES } from "@/lib/run-filters";

export const metadata = { title: "Analytics" };

type SearchParams = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) || undefined;

const DIMENSIONS: { value: AnalyticsDimension; label: string }[] = [
  { value: "language", label: "Language" },
  { value: "scenario_name", label: "Scenario" },
  { value: "bot_adapter", label: "Bot adapter" },
  { value: "mode", label: "Mode" },
  { value: "outcome", label: "Outcome" },
  { value: "suite_id", label: "Suite" },
];

export default function AnalyticsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return (
    <>
      <PageHeader
        title="Analytics"
        description="Computed from stored runs and each run's latest evaluation: nothing sampled, nothing estimated. A pass rate counts decided runs only and always carries its 95% interval and n."
      />
      <PageBody>
        <Suspense fallback={<StatsSkeleton count={4} />}>
          <Analytics searchParams={searchParams} />
        </Suspense>
      </PageBody>
    </>
  );
}

function Verdicts({ tally }: { tally: VerdictTally }) {
  const v = tally.verdicts;
  return (
    <span className="font-mono text-[12px] text-text-2 tabular">
      {v.pass} pass · {v.fail} fail · {v.undetermined} undetermined · {v.not_evaluated} not evaluated
    </span>
  );
}

async function Analytics({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const requested = one(params.group_by);
  const groupBy = DIMENSIONS.some((d) => d.value === requested) ? (requested as AnalyticsDimension) : "language";
  // Exactly the filters the summary and trend endpoints declare.
  const filter = {
    suite_id: one(params.suite_id),
    mode: one(params.mode),
    language: one(params.language),
    scenario_name: one(params.scenario_name),
    bot_adapter: one(params.bot_adapter),
    created_after: one(params.created_after),
    created_before: one(params.created_before),
  };
  const regression = {
    baseline_created_after: one(params.baseline_created_after),
    baseline_created_before: one(params.baseline_created_before),
    candidate_created_after: one(params.candidate_created_after),
    candidate_created_before: one(params.candidate_created_before),
  };
  const wantsRegression = Object.values(regression).some(Boolean);

  let summary: AnalyticsSummary, trend: AnalyticsTrend, result: RegressionResult | null;
  let suites: SuiteSummary[], languages: LanguageCatalogue, adapters: BotAdapters;
  try {
    const { auth } = await loadContext();
    const o = { cache: "no-store" as const, headers: auth };
    [summary, trend, result, suites, languages, adapters] = await Promise.all([
      api.analyticsSummary({ ...o, query: { group_by: groupBy, ...filter } }),
      api.analyticsTrend({ ...o, query: { bucket: "day", ...filter } }),
      wantsRegression
        ? api.regressions({
            ...o,
            query: {
              ...regression,
              // The same scope on both sides, so only the period differs.
              baseline_suite_id: filter.suite_id,
              candidate_suite_id: filter.suite_id,
              baseline_mode: filter.mode,
              candidate_mode: filter.mode,
              baseline_language: filter.language,
              candidate_language: filter.language,
              baseline_scenario_name: filter.scenario_name,
              candidate_scenario_name: filter.scenario_name,
              baseline_bot_adapter: filter.bot_adapter,
              candidate_bot_adapter: filter.bot_adapter,
            },
          })
        : Promise.resolve(null),
      api.suites(o).then((p) => p.items),
      api.languages({ revalidate: 3600 }),
      api.botAdapters(o),
    ]);
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="Analytics could not be loaded" detail={error instanceof ApiError ? error.message : "The analytics request failed."} />
      </Panel>
    );
  }

  const suiteName = new Map(suites.map((s) => [s.id, s.name]));
  const keyLabel = (key: string | null) => {
    if (key === null) return "not recorded";
    if (groupBy === "suite_id") return suiteName.get(key) ?? key.slice(0, 8);
    if (groupBy === "mode" || groupBy === "outcome") return humanise(key) ?? key;
    return key;
  };
  const active = Object.entries(filter).filter(([, v]) => v) as [string, string][];
  const keep = (extra: Record<string, string>) => `/app/analytics?${new URLSearchParams({ ...Object.fromEntries(active), ...extra }).toString()}`;
  const latency = summary.metrics.per_run_median_latency_ms;
  const wer = summary.metrics.wer_pooled;

  return (
    <div className="space-y-6">
      <Panel>
        <form aria-label="Filter analytics" className="grid gap-3 p-4 sm:grid-cols-2 sm:px-5 lg:grid-cols-4 xl:grid-cols-[repeat(6,minmax(0,1fr))_auto] xl:items-end">
          <input type="hidden" name="group_by" value={groupBy} />
          <label>
            <span className="text-[12px] font-medium text-text-3">Suite</span>
            <Select name="suite_id" defaultValue={filter.suite_id ?? ""} className="mt-1">
              <option value="">All suites</option>
              {suites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </label>
          <label>
            <span className="text-[12px] font-medium text-text-3">Language</span>
            <Select name="language" defaultValue={filter.language ?? ""} className="mt-1">
              <option value="">Any</option>
              {languages.languages.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.name}
                </option>
              ))}
            </Select>
          </label>
          <label>
            <span className="text-[12px] font-medium text-text-3">Mode</span>
            <Select name="mode" defaultValue={filter.mode ?? ""} className="mt-1">
              <option value="">Any</option>
              {RUN_MODES.map(([v, t]) => (
                <option key={v} value={v}>
                  {t}
                </option>
              ))}
            </Select>
          </label>
          <label>
            <span className="text-[12px] font-medium text-text-3">Bot adapter</span>
            <Select name="bot_adapter" defaultValue={filter.bot_adapter ?? ""} className="mt-1">
              <option value="">Any</option>
              {adapters.adapters.map((a) => (
                <option key={a.name} value={a.name}>
                  {a.display_name}
                </option>
              ))}
            </Select>
          </label>
          <label>
            <span className="text-[12px] font-medium text-text-3">From</span>
            <Input type="date" name="created_after" defaultValue={filter.created_after} className="mt-1" />
          </label>
          <label>
            <span className="text-[12px] font-medium text-text-3">Before</span>
            <Input type="date" name="created_before" defaultValue={filter.created_before} className="mt-1" />
          </label>
          <div className="flex gap-2">
            <button type="submit" className={buttonClass("secondary", "md")}>
              Apply
            </button>
            {active.length > 0 ? (
              <Link href={`/app/analytics?group_by=${groupBy}`} className={buttonClass("ghost", "md")}>
                Clear
              </Link>
            ) : null}
          </div>
        </form>
      </Panel>

      {summary.overall.runs === 0 ? (
        <Panel>
          <EmptyState
            title={active.length > 0 ? "No runs match these filters" : "No runs to analyse yet"}
            action={
              active.length > 0 ? null : (
                <ButtonLink href="/app/runs/new" tone="primary">
                  Start a test run
                </ButtonLink>
              )
            }
          >
            These views fill from runs you have executed and evaluated. There is no sample data.
          </EmptyState>
        </Panel>
      ) : (
        <>
          {summary.warnings.map((w) => (
            <p key={w} role="note" className="flex gap-2 rounded-lg border border-warn/30 bg-warn-soft px-4 py-3 text-[13px] text-text-2">
              <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warn" />
              {w}
            </p>
          ))}

          <section aria-label="Overall" className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,13rem),1fr))] gap-3">
            <Stat label="Runs" value={summary.overall.runs} detail={<Verdicts tally={summary.overall} />} />
            <Stat
              label="Pass rate"
              value={summary.overall.pass_rate.rate === null ? null : `${Math.round(summary.overall.pass_rate.rate * 100)}%`}
              missing="No decided runs"
              detail={formatPassRate(summary.overall.pass_rate) ?? "Undetermined and unevaluated runs are not counted."}
            />
            <Stat
              label="Word error rate, pooled"
              value={wer.value === null ? null : formatErrorRate(wer.value)}
              missing="No reviewed reference transcripts yet"
              detail={wer.value === null ? "Total errors over total reference words." : `${wer.errors} errors in ${wer.reference_words} words, ${wer.runs_with_references} runs`}
            />
            <Stat
              label="Bot latency, per-run median"
              value={latency.runs === 0 ? null : formatMs(latency.p50)}
              missing="No run measured latency"
              detail={latency.runs === 0 ? latency.note : `p90 ${formatMs(latency.p90)} · ${latency.runs} runs. ${latency.note}`}
            />
          </section>

          <Panel>
            <PanelHeader title="Activity" description="Runs per day (UTC), each counted once by its latest verdict." />
            <PanelBody>
              <VerdictTrend periods={trend.periods} />
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader
              title="Pass rate by group"
              description="A dot is the pass rate and the line its Wilson 95% interval. A wide line means few decided runs: read it before reading the dot."
              actions={
                <nav aria-label="Group by" className="flex flex-wrap gap-1">
                  {DIMENSIONS.map((d) => (
                    <Link
                      key={d.value}
                      href={keep({ group_by: d.value })}
                      aria-current={d.value === groupBy ? "page" : undefined}
                      className={cx(
                        "inline-flex h-8 items-center rounded-md px-2.5 text-[13px] font-medium",
                        d.value === groupBy ? "bg-text text-bg" : "text-text-2 hover:bg-bg-sunk",
                      )}
                    >
                      {d.label}
                    </Link>
                  ))}
                </nav>
              }
            />
            <PanelBody>
              <PassRateIntervals
                caption={`Pass rate by ${DIMENSIONS.find((d) => d.value === groupBy)?.label.toLowerCase()}`}
                rows={summary.groups.map((g) => ({
                  key: String(g.key),
                  label: keyLabel(g.key),
                  rate: g.pass_rate.rate,
                  low: g.pass_rate.ci95_low,
                  high: g.pass_rate.ci95_high,
                  n: g.pass_rate.n,
                }))}
              />
            </PanelBody>
            <details className="border-t border-line">
              <summary className="cursor-pointer px-4 py-3 text-[13px] font-medium text-text sm:px-5">Show as table</summary>
              <TableScroll label="Pass rate by group">
                <Table className="min-w-[40rem]">
                  <thead>
                    <tr>
                      <Th>{DIMENSIONS.find((d) => d.value === groupBy)?.label}</Th>
                      <Th className="text-right">Runs</Th>
                      <Th>Pass rate (95% interval, n)</Th>
                      <Th>Verdicts</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.groups.map((g) => (
                      <tr key={String(g.key)}>
                        <Td className="font-medium text-text">{keyLabel(g.key)}</Td>
                        <Td className="text-right font-mono tabular">{g.runs}</Td>
                        <Td className="font-mono text-[12px]">{formatPassRate(g.pass_rate) ?? "No decided runs"}</Td>
                        <Td>
                          <Verdicts tally={g} />
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </TableScroll>
            </details>
          </Panel>
        </>
      )}

      <div className="grid min-w-0 gap-6 lg:grid-cols-2">
        <Panel>
          <PanelHeader
            title="Regression check"
            icon={<FlaskConical aria-hidden="true" className="size-4" />}
            description="Pass rate of runs created in one period against another, within the filters above, by Fisher's exact test. Called a regression only at p < 0.05 with enough decided runs on each side."
          />
          <form action="/app/analytics" method="get" className="grid gap-3 p-4 sm:grid-cols-2 sm:px-5">
            <input type="hidden" name="group_by" value={groupBy} />
            {active.map(([k, v]) => (
              <input key={k} type="hidden" name={k} value={v} />
            ))}
            <DateField name="baseline_created_after" label="Baseline from" value={regression.baseline_created_after} />
            <DateField name="baseline_created_before" label="Baseline before" value={regression.baseline_created_before} />
            <DateField name="candidate_created_after" label="Candidate from" value={regression.candidate_created_after} />
            <DateField name="candidate_created_before" label="Candidate before" value={regression.candidate_created_before} />
            <button type="submit" className={buttonClass("primary", "md", "justify-self-start")}>
              Run the check
            </button>
          </form>
          {result ? (
            <div role="status" className="border-t border-line p-4 sm:px-5">
              <p className="text-[16px] font-semibold text-text">{humanise(result.conclusion)}</p>
              <p className="mt-1 text-[13px] leading-relaxed text-text-2">{result.reason}</p>
              <dl className="mt-4 grid gap-4 sm:grid-cols-3">
                <Fact label="Baseline">{formatPassRate(result.baseline.pass_rate) ?? "No decided runs"}</Fact>
                <Fact label="Candidate">{formatPassRate(result.candidate.pass_rate) ?? "No decided runs"}</Fact>
                <Fact label="p-value, two-sided" mono>
                  {result.p_value === null ? <NotReported what="a side has no decided runs" /> : result.p_value.toFixed(4)}
                </Fact>
              </dl>
              {result.warnings.map((w) => (
                <p key={w} className="mt-2 text-[12px] text-warn">
                  {w}
                </p>
              ))}
            </div>
          ) : null}
        </Panel>

        <Panel>
          <PanelHeader title="Export and compare" description="The same runs, out of the browser or side by side." />
          <PanelBody className="space-y-4">
            <div>
              <p className="text-[14px] font-medium text-text">Runs as CSV</p>
              <p className="mt-0.5 text-[13px] text-text-3">Every run within the filters above, with its latest verdict.</p>
              <a href={runsCsvUrl(filter)} download className={buttonClass("secondary", "sm", "mt-2")}>
                <Download aria-hidden="true" className="size-3.5" />
                Download CSV
              </a>
            </div>
            <div className="border-t border-line pt-4">
              <p className="text-[14px] font-medium text-text">Compare two runs</p>
              <p className="mt-0.5 text-[13px] text-text-3">Verdict and metric deltas between two evaluated runs. Two runs support no statistical claim.</p>
              <ButtonLink href="/app/compare" tone="secondary" size="sm" className="mt-2">
                Open compare
              </ButtonLink>
            </div>
            {summary.evaluator_versions.length > 0 ? (
              <p className="border-t border-line pt-4 font-mono text-[12px] text-text-3">Evaluators in these figures: {summary.evaluator_versions.join(", ")}</p>
            ) : null}
          </PanelBody>
        </Panel>
      </div>
    </div>
  );
}

function DateField({ name, label, value }: { name: string; label: string; value?: string }) {
  return (
    <label>
      <span className="text-[12px] font-medium text-text-3">{label}</span>
      <Input type="date" name={name} defaultValue={value} className="mt-1" />
    </label>
  );
}
