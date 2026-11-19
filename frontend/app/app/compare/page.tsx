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
import type { ComparedRun, RunComparison } from "@/lib/api/types";
import { humanise, shortId } from "@/lib/format";
import { metricLabel } from "@/lib/evaluation";
import { PrintButton } from "@/components/ui/print-button";

export const metadata = { title: "Compare runs" };

type SearchParams = Record<string, string | string[] | undefined>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function one(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value || undefined;
}

export default function ComparePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return (
    <>
      <PageHeader
        title="Compare runs"
        description="Two evaluated runs side by side. An observation, not a significant result - use the regression check on Analytics for groups of runs."
        actions={<PrintButton />}
      />
      <PageBody>
        <Suspense fallback={<TableSkeleton />}>
          <Comparison searchParams={searchParams} />
        </Suspense>
      </PageBody>
    </>
  );
}

const CHANGE_TONE: Record<string, string> = {
  better: "text-ok",
  worse: "text-bad",
  unchanged: "text-text-muted",
  not_comparable: "text-text-dim",
};

function format(value: number | null): string | null {
  return value === null ? null : Number.isInteger(value) ? String(value) : value.toFixed(4);
}

async function Comparison({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const auth = await sessionHeaders();
  const params = await searchParams;
  const baseline = one(params.baseline);
  const candidate = one(params.candidate);
  if (!baseline || !candidate || !UUID.test(baseline) || !UUID.test(candidate)) {
    return (
      <Panel>
        <EmptyState
          title="Choose two runs"
          action={
            <Link href="/app/analytics" className={buttonClass("primary", "sm")}>
              Back to analytics
            </Link>
          }
        >
          Pick a baseline and a candidate on the Analytics page. Both must have been evaluated.
        </EmptyState>
      </Panel>
    );
  }

  let result: RunComparison;
  try {
    result = await api.compareRuns(baseline, candidate, { cache: "no-store", headers: auth });
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState
          title="These runs could not be compared"
          detail={error instanceof ApiError ? error.message : "The comparison failed."}
        />
      </Panel>
    );
  }

  return (
    <div className="grid min-w-0 gap-5">
      <Panel className="p-4 sm:p-5">
        <p className="text-[15px] font-semibold text-text">Verdict {humanise(result.verdict_change)}</p>
        <p className="mt-1 text-[13px] text-text-muted">{result.statistical_note}</p>
        {result.warnings.map((warning) => (
          <p key={warning} role="note" className="mt-2 text-[13px] text-warn">
            Not like-for-like: {warning}
          </p>
        ))}
      </Panel>

      <div className="grid min-w-0 gap-5 lg:grid-cols-2">
        <Side title="Baseline" run={result.baseline} />
        <Side title="Candidate" run={result.candidate} />
      </div>

      <Panel>
        <PanelHeader title="Metrics" description="Direction is per metric: lower is better for error rates and latency." />
        <TableScroll>
          <table className="w-full min-w-max text-left text-[13px]">
            <thead>
              <tr>
                <Th>Metric</Th>
                <Th>Baseline</Th>
                <Th>Candidate</Th>
                <Th>Delta</Th>
                <Th>Change</Th>
              </tr>
            </thead>
            <tbody>
              {result.metric_deltas.map((delta) => (
                <tr key={delta.metric} className="border-t border-line">
                  <Td className="font-medium text-text">{metricLabel(delta.metric)}</Td>
                  <Td className="font-mono tabular-nums">{format(delta.baseline) ?? <NotReported />}</Td>
                  <Td className="font-mono tabular-nums">{format(delta.candidate) ?? <NotReported />}</Td>
                  <Td className="font-mono tabular-nums">{format(delta.delta) ?? "—"}</Td>
                  <Td className={cx(CHANGE_TONE[delta.change])}>{humanise(delta.change)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      </Panel>
    </div>
  );
}

function Side({ title, run }: { title: string; run: ComparedRun }) {
  return (
    <Panel>
      <PanelHeader
        title={title}
        actions={
          <Link href={`/app/runs/${run.run_id}`} className={buttonClass("default", "sm")}>
            Run {shortId(run.run_id)}
          </Link>
        }
      />
      <dl className="grid gap-3 p-4 sm:grid-cols-2 sm:p-5">
        <Fact label="Verdict">{humanise(run.verdict)}</Fact>
        <Fact label="Scenario">{run.scenario_name ?? <NotReported />}</Fact>
        <Fact label="Language" mono>{run.language ?? <NotReported />}</Fact>
        <Fact label="Mode">{humanise(run.mode) ?? <NotReported />}</Fact>
        <Fact label="Evaluator" mono>{run.evaluator_version}</Fact>
        <Fact label="Evidence fingerprint" mono hint="SHA-256 of what the evaluation read">
          {run.evidence_fingerprint.slice(0, 16)}…
        </Fact>
      </dl>
    </Panel>
  );
}
