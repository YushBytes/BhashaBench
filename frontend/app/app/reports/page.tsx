import Link from "next/link";
import { Suspense } from "react";
import { Download, FileJson, FileSpreadsheet, FileText, GitCompareArrows, Layers, Printer } from "lucide-react";

import { PageBody, PageHeader } from "@/components/shell/page";
import { Select } from "@/components/ui/field";
import { EmptyState, ErrorState, Panel, PanelHeader, Table, TableScroll, TableSkeleton, Td, Th, buttonClass, cx } from "@/components/ui/primitives";
import { ModeBadge, OutcomeBadge } from "@/components/ui/status";
import { ApiError, api, runExportUrl, runsCsvUrl } from "@/lib/api/client";
import { loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { Page, RunSummary } from "@/lib/api/types";
import { formatTimestampShort, shortId } from "@/lib/format";

export const metadata = { title: "Reports" };

type SearchParams = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) || undefined;
const FINISHED = [
  ["completed", "Completed"],
  ["failed", "Failed"],
  ["cancelled", "Cancelled"],
] as const;

export default function ReportsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return (
    <>
      <PageHeader
        title="Reports"
        description="A report here is a run's own evidence: its turns, recordings, stage timings, configuration and latest evaluation, exported as JSON or CSV, or saved from its page as a PDF. Nothing is summarised beyond what was stored."
      />
      <PageBody>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Kind icon={FileText} title="Run report" body="Open a run and use Save as PDF. Every tab prints, including the evaluation and its limitations." />
          <Kind icon={FileJson} title="Run evidence" body="JSON or CSV of one run with its latest evaluation, project and suite." />
          <Kind icon={FileSpreadsheet} title="All runs" body="CSV of every run you can see, with its latest verdict, filtered on Analytics." href={runsCsvUrl()} cta="Download CSV" />
          <Kind icon={GitCompareArrows} title="Comparison" body="Two runs side by side, printable from the Compare page." internal="/app/compare" cta="Open compare" />
        </div>
        <Suspense fallback={<TableSkeleton rows={6} />}>
          <Finished searchParams={searchParams} />
        </Suspense>
        <p className="flex items-center gap-2 text-[12px] text-text-3">
          <Layers aria-hidden="true" className="size-3.5" />A suite&rsquo;s scenarios export as a bundle from the suite&rsquo;s own page.
        </p>
      </PageBody>
    </>
  );
}

function Kind({ icon: Icon, title, body, href, internal, cta }: { icon: typeof FileText; title: string; body: string; href?: string; internal?: string; cta?: string }) {
  return (
    <div className="flex flex-col rounded-lg border border-line bg-bg p-4 shadow-1">
      <Icon aria-hidden="true" className="size-5 text-text-2" strokeWidth={1.75} />
      <p className="mt-3 text-[14px] font-semibold text-text">{title}</p>
      <p className="mt-1 flex-1 text-[13px] leading-relaxed text-text-3">{body}</p>
      {href && cta ? (
        <a href={href} download className={buttonClass("secondary", "sm", "mt-3 self-start")}>
          <Download aria-hidden="true" className="size-3.5" />
          {cta}
        </a>
      ) : internal && cta ? (
        <Link href={internal} className={buttonClass("secondary", "sm", "mt-3 self-start")}>
          {cta}
        </Link>
      ) : null}
    </div>
  );
}

async function Finished({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const requested = one(params.status);
  const status = FINISHED.some(([v]) => v === requested) ? requested : "completed";
  let runs: Page<RunSummary>;
  try {
    const { auth } = await loadContext();
    runs = await api.runs({ cache: "no-store", headers: auth, query: { status, limit: 50 } });
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="Runs could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }
  return (
    <Panel>
      <PanelHeader
        title="Run reports"
        description={`${runs.total} ${status} run${runs.total === 1 ? "" : "s"}${runs.total > runs.items.length ? `, the newest ${runs.items.length} shown` : ""}.`}
        actions={
          <form className="flex items-center gap-2">
            <label htmlFor="report-status" className="sr-only">
              Status
            </label>
            <Select id="report-status" name="status" defaultValue={status} className="h-8 w-36 text-[13px]">
              {FINISHED.map(([v, t]) => (
                <option key={v} value={v}>
                  {t}
                </option>
              ))}
            </Select>
            <button type="submit" className={buttonClass("secondary", "sm")}>
              Show
            </button>
          </form>
        }
      />
      {runs.items.length === 0 ? (
        <EmptyState title={`No ${status} runs`}>Reports appear here once runs finish.</EmptyState>
      ) : (
        <TableScroll label="Run reports">
          <Table className="min-w-[52rem]">
            <thead>
              <tr>
                <Th>Run</Th>
                <Th>Outcome</Th>
                <Th>Mode</Th>
                <Th>Finished</Th>
                <Th className="text-right">Export</Th>
              </tr>
            </thead>
            <tbody>
              {runs.items.map((r) => (
                <tr key={r.run_id} className="hover:bg-bg-soft">
                  <Td className="max-w-[20rem]">
                    <Link href={`/app/runs/${r.run_id}`} className="block truncate font-medium text-text hover:text-accent">
                      {r.scenario_name}
                    </Link>
                    <span className="font-mono text-[11px] text-text-3">
                      {shortId(r.run_id)} · {r.language}
                    </span>
                  </Td>
                  <Td>
                    <OutcomeBadge outcome={r.outcome} />
                  </Td>
                  <Td>
                    <ModeBadge mode={r.mode} />
                  </Td>
                  <Td className="whitespace-nowrap font-mono text-[12px] text-text-3">{formatTimestampShort(r.finished_at ?? r.created_at)}</Td>
                  <Td className="text-right">
                    <span className="inline-flex gap-1">
                      <Link href={`/app/runs/${r.run_id}`} className={cx(buttonClass("ghost", "sm"))} title="Open the report and save it as PDF">
                        <Printer aria-hidden="true" className="size-3.5" />
                        PDF
                      </Link>
                      <a href={runExportUrl(r.run_id, "json")} download className={buttonClass("ghost", "sm")}>
                        JSON
                      </a>
                      <a href={runExportUrl(r.run_id, "csv")} download className={buttonClass("ghost", "sm")}>
                        CSV
                      </a>
                    </span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableScroll>
      )}
    </Panel>
  );
}
