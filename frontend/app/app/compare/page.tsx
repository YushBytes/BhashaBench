import Link from "next/link";
import { Suspense } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, Minus } from "lucide-react";

import { ComparePicker, type PickableRun } from "@/components/runs/compare-picker";
import { PageBody, PageHeader } from "@/components/shell/page";
import { PrintButton } from "@/components/ui/interactive";
import {
  EmptyState,
  ErrorState,
  Fact,
  NotReported,
  Panel,
  PanelBody,
  PanelHeader,
  Table,
  TableScroll,
  TableSkeleton,
  Td,
  Th,
  cx,
} from "@/components/ui/primitives";
import { Badge, VerdictBadge } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import { loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { ComparedRun, RunComparison, RunSummary } from "@/lib/api/types";
import { metricLabel } from "@/lib/evaluation";
import { formatTimestampShort, humanise } from "@/lib/format";

export const metadata = { title: "Compare runs" };

type SearchParams = Record<string, string | string[] | undefined>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) || undefined;

export default function ComparePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return (
    <>
      <PageHeader
        title="Compare two runs"
        description="Two evaluated runs side by side. An observation, not a significant result: comparison is pairwise, and groups of runs go through the regression check on Analytics."
        actions={<PrintButton />}
      />
      <PageBody>
        <Suspense fallback={<TableSkeleton rows={4} />}>
          <Compare searchParams={searchParams} />
        </Suspense>
      </PageBody>
    </>
  );
}

const pick = (r: RunSummary): PickableRun => ({
  id: r.run_id,
  label: r.scenario_name,
  detail: [r.language, humanise(r.mode), r.noise_profile ? humanise(r.noise_profile) : null, formatTimestampShort(r.created_at)].filter(Boolean).join(" · "),
});

async function Compare({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const baseline = one(params.baseline);
  const candidate = one(params.candidate);
  const chosen = baseline && candidate && UUID.test(baseline) && UUID.test(candidate);

  let runs: RunSummary[];
  let result: RunComparison | null = null;
  let failure: string | null = null;
  try {
    const { auth } = await loadContext();
    runs = (await api.runs({ cache: "no-store", headers: auth, query: { status: "completed", limit: 100 } })).items;
    if (chosen) {
      result = await api.compareRuns(baseline, candidate, { cache: "no-store", headers: auth }).catch((error: unknown) => {
        if (error instanceof ApiError && error.status !== 401) {
          failure = error.message;
          return null;
        }
        throw error;
      });
    }
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="Runs could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }

  return (
    <div className="space-y-6">
      <Panel className="no-print">
        <PanelHeader title="Choose the runs" description={`The ${runs.length} most recent completed runs you can see. Both must have been evaluated; the comparison says so if one has not.`} />
        <PanelBody>
          {runs.length < 2 ? (
            <EmptyState title="Two completed runs are needed">Complete and evaluate at least two runs, then compare them here.</EmptyState>
          ) : (
            <ComparePicker runs={runs.map(pick)} baseline={baseline} candidate={candidate} />
          )}
        </PanelBody>
      </Panel>

      {failure ? (
        <Panel>
          <ErrorState title="These runs could not be compared" detail={failure} />
        </Panel>
      ) : null}

      {result ? <Result result={result} /> : null}
    </div>
  );
}

const CHANGE: Record<string, { icon: typeof ArrowUp; className: string }> = {
  better: { icon: ArrowUp, className: "text-ok" },
  worse: { icon: ArrowDown, className: "text-bad" },
  unchanged: { icon: Minus, className: "text-text-3" },
  not_comparable: { icon: Minus, className: "text-text-3" },
};

function fmt(value: number | null): string | null {
  return value === null ? null : Number.isInteger(value) ? String(value) : value.toFixed(4);
}

function Result({ result }: { result: RunComparison }) {
  return (
    <>
      <Panel>
        <PanelBody className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-[13px] text-text-3">Verdict change</span>
            <Badge tone={result.verdict_change === "regressed" ? "bad" : result.verdict_change === "improved" ? "ok" : "idle"}>
              {humanise(result.verdict_change)}
            </Badge>
            {!result.comparable ? <Badge tone="warn">Not like for like</Badge> : null}
          </div>
          <p className="text-[13px] leading-relaxed text-text-2">{result.statistical_note}</p>
          {result.warnings.map((w) => (
            <p key={w} role="note" className="flex gap-2 text-[13px] text-warn">
              <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              {w}
            </p>
          ))}
        </PanelBody>
      </Panel>

      <div className="grid min-w-0 gap-6 lg:grid-cols-2">
        <Side title="Baseline" run={result.baseline} />
        <Side title="Candidate" run={result.candidate} />
      </div>

      <Panel>
        <PanelHeader title="Metrics" description="Direction is per metric: lower is better for error rates and latency. A metric either run lacks is not compared." />
        <TableScroll label="Metric deltas">
          <Table className="min-w-[40rem]">
            <thead>
              <tr>
                <Th>Metric</Th>
                <Th className="text-right">Baseline</Th>
                <Th className="text-right">Candidate</Th>
                <Th className="text-right">Delta</Th>
                <Th>Change</Th>
              </tr>
            </thead>
            <tbody>
              {result.metric_deltas.map((d) => {
                const change = CHANGE[d.change] ?? CHANGE.not_comparable;
                return (
                  <tr key={d.metric}>
                    <Td className="font-medium text-text">{metricLabel(d.metric)}</Td>
                    <Td className="text-right font-mono tabular">{fmt(d.baseline) ?? <NotReported />}</Td>
                    <Td className="text-right font-mono tabular">{fmt(d.candidate) ?? <NotReported />}</Td>
                    <Td className="text-right font-mono tabular">{fmt(d.delta) ?? "—"}</Td>
                    <Td>
                      <span className={cx("inline-flex items-center gap-1 text-[13px] font-medium", change.className)}>
                        <change.icon aria-hidden="true" className="size-3.5" />
                        {humanise(d.change)}
                      </span>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </TableScroll>
      </Panel>
    </>
  );
}

function Side({ title, run }: { title: string; run: ComparedRun }) {
  return (
    <Panel>
      <PanelHeader
        title={title}
        actions={
          <Link href={`/app/runs/${run.run_id}`} className="font-mono text-[12px] text-accent hover:underline">
            {run.run_id.slice(0, 8)}
          </Link>
        }
      />
      <PanelBody>
        <dl className="grid gap-4 sm:grid-cols-2">
          <Fact label="Verdict">
            <VerdictBadge verdict={run.verdict} />
          </Fact>
          <Fact label="Scenario">{run.scenario_name ?? <NotReported />}</Fact>
          <Fact label="Language" mono>
            {run.language ?? <NotReported />}
          </Fact>
          <Fact label="Mode">{humanise(run.mode) ?? <NotReported />}</Fact>
          <Fact label="Bot adapter" mono>
            {run.bot_adapter ?? <NotReported />}
          </Fact>
          <Fact label="Bot" hint="The connected bot this run tested, as recorded when it was created.">
            {run.bot_integration ? `${run.bot_integration.name} (${run.bot_integration.host})` : "A server adapter, not a connected bot"}
          </Fact>
          <Fact label="Evaluator" mono>
            {run.evaluator_version}
          </Fact>
          <Fact label="Evidence fingerprint" mono hint="SHA-256 of what the evaluation read.">
            {run.evidence_fingerprint.slice(0, 16)}…
          </Fact>
        </dl>
      </PanelBody>
    </Panel>
  );
}
