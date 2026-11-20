import Link from "next/link";
import { Suspense } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Circle,
  FileText,
  FolderPlus,
  Gauge,
  ListPlus,
  PlayCircle,
} from "lucide-react";

import { VerdictTrend } from "@/components/charts/verdict-trend";
import { RunsTable } from "@/components/domain/runs-table";
import { PageBody, PageHeader } from "@/components/shell/page";
import {
  ButtonLink,
  EmptyState,
  ErrorState,
  Panel,
  PanelHeader,
  Stat,
  StatsSkeleton,
  TableSkeleton,
  cx,
} from "@/components/ui/primitives";
import { HealthBadge } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import { loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { AnalyticsSummary, AnalyticsTrend, ApiHealth, Page, RunSummary } from "@/lib/api/types";
import { formatErrorRate, formatMs } from "@/lib/format";

export const metadata = { title: "Overview" };

export default function OverviewPage() {
  return (
    <>
      <PageHeader
        title="Overview"
        description="Your testing activity across every workspace you belong to. Every figure is read from stored runs and their latest evaluation."
        actions={
          <>
            <ButtonLink href="/app/scenarios/new" tone="secondary">
              New scenario
            </ButtonLink>
            <ButtonLink href="/app/runs/new" tone="primary">
              <PlayCircle aria-hidden="true" className="size-4" />
              New test run
            </ButtonLink>
          </>
        }
      />
      <PageBody>
        <Suspense fallback={<OverviewSkeleton />}>
          <Overview />
        </Suspense>
      </PageBody>
    </>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-6">
      <StatsSkeleton count={4} />
      <TableSkeleton rows={4} />
    </div>
  );
}

async function Overview() {
  let context;
  let summary: AnalyticsSummary;
  let trend: AnalyticsTrend;
  let recent: Page<RunSummary>;
  let failed: Page<RunSummary>;
  let suiteTotal: number;
  let scenarioTotal: number;
  let health: ApiHealth | null;
  try {
    context = await loadContext();
    const auth = context.auth;
    [summary, trend, recent, failed, suiteTotal, scenarioTotal, health] = await Promise.all([
      api.analyticsSummary({ cache: "no-store", headers: auth }),
      api.analyticsTrend({ cache: "no-store", headers: auth, query: { bucket: "day" } }),
      api.runs({ cache: "no-store", headers: auth, query: { limit: 6 } }),
      api.runs({ cache: "no-store", headers: auth, query: { limit: 4, status: "failed" } }),
      api.suites({ cache: "no-store", headers: auth, query: { limit: 1 } }).then((p) => p.total),
      api.scenarios({ cache: "no-store", headers: auth, query: { limit: 1 } }).then((p) => p.total),
      api.health({ cache: "no-store" }).catch(() => null),
    ]);
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState
          title="The overview could not be loaded"
          detail={error instanceof ApiError ? error.message : "The API did not answer."}
        />
      </Panel>
    );
  }

  const overall = summary.overall;
  const evaluated = overall.runs - overall.verdicts.not_evaluated;
  const steps = [
    { done: context.projects.length > 0, title: "Have a project", body: "Sign-up creates a Default project.", href: "/app/projects" },
    { done: suiteTotal > 0, title: "Create a test suite", body: "Suites group the scenarios you run together.", href: "/app/suites?create=1" },
    { done: scenarioTotal > 0, title: "Add a scenario", body: "Start from a shipped reference scenario or build your own.", href: "/app/scenarios/new" },
    { done: overall.runs > 0, title: "Run a test", body: "Offline first, to check the caller's logic, then against your bot.", href: "/app/runs/new" },
    { done: evaluated > 0, title: "Evaluate a run", body: "A verdict with a reason for every criterion.", href: "/app/runs?status=completed" },
  ];
  const remaining = steps.filter((s) => !s.done).length;
  const latency = summary.metrics.per_run_median_latency_ms;
  const wer = summary.metrics.wer_pooled;
  const passRate = overall.pass_rate;

  return (
    <div className="space-y-6">
      {remaining > 0 ? (
        <Panel>
          <PanelHeader
            title="Get started"
            description={`${steps.length - remaining} of ${steps.length} done. Each step is checked against what exists in your workspaces.`}
          />
          <ol className="grid divide-y divide-line md:grid-cols-5 md:divide-x md:divide-y-0">
            {steps.map((step, index) => (
              <li key={step.title}>
                <Link
                  href={step.href}
                  className={cx("flex h-full gap-3 p-4 transition-colors hover:bg-bg-soft md:flex-col", step.done && "opacity-70")}
                >
                  {step.done ? (
                    <CheckCircle2 aria-hidden="true" className="size-5 shrink-0 text-ok" />
                  ) : (
                    <Circle aria-hidden="true" className="size-5 shrink-0 text-text-3" />
                  )}
                  <span className="min-w-0">
                    <span className="block text-[14px] font-medium text-text">
                      <span className="sr-only">{step.done ? "Done: " : `Step ${index + 1}: `}</span>
                      {step.title}
                    </span>
                    <span className="mt-0.5 block text-[12px] leading-relaxed text-text-3">{step.body}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        </Panel>
      ) : null}

      <section aria-label="Key figures" className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,13rem),1fr))] gap-3">
        <Stat label="Projects" value={context.projects.length} detail={`${suiteTotal} suites · ${scenarioTotal} scenarios`} />
        <Stat
          label="Test runs"
          value={overall.runs}
          detail={`${overall.verdicts.pass} pass · ${overall.verdicts.fail} fail · ${overall.verdicts.undetermined} undetermined · ${overall.verdicts.not_evaluated} not evaluated`}
        />
        <Stat
          label="Pass rate"
          value={passRate.rate === null ? null : `${Math.round(passRate.rate * 100)}%`}
          missing="No decided runs yet"
          detail={
            passRate.rate === null || passRate.ci95_low === null || passRate.ci95_high === null
              ? "Counts passes over decided runs only."
              : `95% interval ${Math.round(passRate.ci95_low * 100)}–${Math.round(passRate.ci95_high * 100)}%, n = ${passRate.n}`
          }
        />
        <Stat
          label="Bot latency, median"
          value={latency.runs === 0 ? null : formatMs(latency.p50)}
          missing="No run measured latency yet"
          detail={latency.runs === 0 ? "Measured on runs that exchange with a bot." : `p90 ${formatMs(latency.p90)} across ${latency.runs} runs`}
          icon={<Gauge aria-hidden="true" className="size-4" />}
        />
        <Stat
          label="Word error rate, pooled"
          value={wer.value === null ? null : formatErrorRate(wer.value)}
          missing="No reviewed reference transcripts yet"
          detail={wer.value === null ? "Needs a reference on at least one bot turn." : `${wer.reference_words} words across ${wer.runs_with_references} runs`}
        />
      </section>

      {summary.warnings.length > 0 ? (
        <Panel className="border-warn/30">
          {summary.warnings.map((warning) => (
            <p key={warning} role="note" className="flex gap-2 px-4 py-3 text-[13px] text-text-2 sm:px-5">
              <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warn" />
              {warning}
            </p>
          ))}
        </Panel>
      ) : null}

      <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Panel>
          <PanelHeader
            title="Activity"
            description="Runs grouped by the day they were created, each counted by its latest verdict."
            actions={
              <ButtonLink href="/app/analytics" tone="ghost" size="sm">
                Analytics <ArrowRight aria-hidden="true" className="size-3.5" />
              </ButtonLink>
            }
          />
          <div className="p-4 sm:p-5">
            {trend.periods.length === 0 ? (
              <EmptyState title="No runs yet">The chart fills from runs you execute. There is no sample data.</EmptyState>
            ) : (
              <VerdictTrend periods={trend.periods.slice(-30)} />
            )}
          </div>
        </Panel>

        <Panel>
          <PanelHeader title="Quick actions" />
          <ul className="divide-y divide-line">
            {[
              { href: "/app/runs/new", label: "Run a test", body: "Pick a scenario, a mode and conditions.", icon: PlayCircle },
              { href: "/app/scenarios/new", label: "Build a scenario", body: "Guided editor, validated by the server.", icon: ListPlus },
              { href: "/app/projects?create=1", label: "Create a project", body: "Admins and owners.", icon: FolderPlus },
              { href: "/app/bots", label: "Check bot adapters", body: "What this deployment can talk to.", icon: Bot },
              { href: "/app/reports", label: "Export a report", body: "JSON, CSV or a printable PDF.", icon: FileText },
            ].map((action) => (
              <li key={action.href}>
                <Link href={action.href} className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-bg-soft sm:px-5">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-md border border-line bg-bg-soft text-text-2">
                    <action.icon aria-hidden="true" className="size-4" strokeWidth={1.75} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[14px] font-medium text-text">{action.label}</span>
                    <span className="block text-[12px] text-text-3">{action.body}</span>
                  </span>
                  <ArrowRight aria-hidden="true" className="size-4 text-text-3 transition-transform group-hover:translate-x-0.5" />
                </Link>
              </li>
            ))}
          </ul>
          {health ? (
            <div className="flex items-center justify-between gap-2 border-t border-line px-4 py-3 text-[12px] text-text-3 sm:px-5">
              <span>
                API {health.version} · {health.environment}
              </span>
              <HealthBadge status={health.status} />
            </div>
          ) : null}
        </Panel>
      </div>

      <Panel>
        <PanelHeader
          title="Recent runs"
          actions={
            <ButtonLink href="/app/runs" tone="ghost" size="sm">
              All runs <ArrowRight aria-hidden="true" className="size-3.5" />
            </ButtonLink>
          }
        />
        {recent.items.length === 0 ? (
          <EmptyState
            title="No runs yet"
            action={
              <ButtonLink href="/app/runs/new" tone="primary">
                Start a test run
              </ButtonLink>
            }
          >
            A run executes one scenario and keeps every turn, recording and timing it produced.
          </EmptyState>
        ) : (
          <RunsTable runs={recent.items} compact />
        )}
      </Panel>

      {failed.items.length > 0 ? (
        <Panel>
          <PanelHeader
            title="Recent execution failures"
            description="Runs that failed to complete. The run page says which stage failed and whose side it was on."
            actions={
              <ButtonLink href="/app/runs?status=failed" tone="ghost" size="sm">
                {failed.total} failed <ArrowRight aria-hidden="true" className="size-3.5" />
              </ButtonLink>
            }
          />
          <ul className="divide-y divide-line">
            {failed.items.map((run) => (
              <li key={run.run_id}>
                <Link href={`/app/runs/${run.run_id}`} className="block px-4 py-3 transition-colors hover:bg-bg-soft sm:px-5">
                  <span className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-[14px] font-medium text-text">{run.scenario_name}</span>
                    <span className="font-mono text-[11px] text-text-3">{run.run_id.slice(0, 8)}</span>
                  </span>
                  <span className="mt-1 block truncate font-mono text-[12px] text-bad">{run.error ?? run.outcome ?? "failed"}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  );
}
