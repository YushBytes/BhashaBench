import Link from "next/link";
import { Suspense } from "react";
import { ChevronLeft, ChevronRight, Download, PlayCircle, Search } from "lucide-react";

import { RunsTable } from "@/components/domain/runs-table";
import { PageBody, PageHeader } from "@/components/shell/page";
import { Input, Select } from "@/components/ui/field";
import { ButtonLink, EmptyState, ErrorState, Panel, TableSkeleton, buttonClass, cx } from "@/components/ui/primitives";
import { ApiError, api, runsCsvUrl } from "@/lib/api/client";
import { loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { LanguageCatalogue, Page, RunSummary, SuiteSummary } from "@/lib/api/types";
import { RUN_MODES, RUN_OUTCOMES, RUN_STATUSES } from "@/lib/run-filters";

export const metadata = { title: "Test runs" };

type SearchParams = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) || undefined;
const PAGE = 25;

export default function RunsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return (
    <>
      <PageHeader
        title="Test runs"
        description="Every run you can see, newest first. A filter value is checked against the API's own vocabulary, so a list here is never silently unfiltered."
        actions={
          <ButtonLink href="/app/runs/new" tone="primary">
            <PlayCircle aria-hidden="true" className="size-4" />
            New test run
          </ButtonLink>
        }
      />
      <PageBody>
        <Suspense fallback={<TableSkeleton rows={8} />}>
          <Runs searchParams={searchParams} />
        </Suspense>
      </PageBody>
    </>
  );
}

async function Runs({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const filters = {
    status: one(params.status),
    mode: one(params.mode),
    outcome: one(params.outcome),
    language: one(params.language),
    scenario: one(params.scenario),
    suite_id: one(params.suite_id),
  };
  const offset = Math.max(0, Number(one(params.offset) ?? 0) || 0);
  let runs: Page<RunSummary>;
  let languages: LanguageCatalogue;
  let suites: SuiteSummary[];
  let suiteNames: Map<string, string>;
  try {
    const context = await loadContext();
    [runs, languages, suites] = await Promise.all([
      api.runs({ cache: "no-store", headers: context.auth, query: { ...filters, limit: PAGE, offset } }),
      api.languages({ revalidate: 3600 }),
      api.suites({ cache: "no-store", headers: context.auth }).then((p) => p.items),
    ]);
    const projectName = new Map(context.projects.map((p) => [p.id, p.name]));
    suiteNames = new Map(suites.map((s) => [s.id, `${projectName.get(s.project_id) ?? "Project"} / ${s.name}`]));
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="Runs could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }

  const active = Object.entries(filters).filter(([, v]) => v);
  const pageLink = (to: number) => {
    const q = new URLSearchParams(active as [string, string][]);
    if (to > 0) q.set("offset", String(to));
    const s = q.toString();
    return `/app/runs${s ? `?${s}` : ""}`;
  };

  return (
    <Panel>
      <form aria-label="Filter runs" className="grid gap-3 border-b border-line p-4 sm:grid-cols-2 sm:px-5 lg:grid-cols-[minmax(0,1.4fr)_repeat(4,minmax(0,1fr))_auto] lg:items-end">
        <label>
          <span className="text-[12px] font-medium text-text-3">Scenario name</span>
          <span className="relative mt-1 block">
            <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-text-3" />
            <Input name="scenario" type="search" defaultValue={filters.scenario ?? ""} placeholder="Exact name" className="pl-8" />
          </span>
        </label>
        <FilterSelect name="status" label="Status" value={filters.status} options={RUN_STATUSES} />
        <FilterSelect name="mode" label="Mode" value={filters.mode} options={RUN_MODES} />
        <FilterSelect name="outcome" label="Outcome" value={filters.outcome} options={RUN_OUTCOMES} />
        <label>
          <span className="text-[12px] font-medium text-text-3">Language</span>
          <Select name="language" defaultValue={filters.language ?? ""} className="mt-1">
            <option value="">Any</option>
            {languages.languages.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name}
              </option>
            ))}
          </Select>
        </label>
        <div className="flex gap-2">
          {filters.suite_id ? <input type="hidden" name="suite_id" value={filters.suite_id} /> : null}
          <button type="submit" className={buttonClass("secondary", "md")}>
            Apply
          </button>
          {active.length > 0 ? (
            <Link href="/app/runs" className={buttonClass("ghost", "md")}>
              Clear
            </Link>
          ) : null}
        </div>
      </form>

      {filters.suite_id ? (
        <p className="border-b border-line bg-bg-soft px-4 py-2 text-[12px] text-text-3 sm:px-5">
          Only suite <span className="font-medium text-text-2">{suiteNames.get(filters.suite_id) ?? filters.suite_id}</span>
        </p>
      ) : null}

      {runs.items.length === 0 ? (
        <EmptyState
          title={active.length > 0 ? "No runs match these filters" : "No runs yet"}
          action={
            active.length > 0 ? null : (
              <ButtonLink href="/app/runs/new" tone="primary">
                Start a test run
              </ButtonLink>
            )
          }
        >
          {active.length > 0 ? "Change or clear the filters." : "A run executes one scenario and keeps every turn, recording and timing it produced."}
        </EmptyState>
      ) : (
        <RunsTable runs={runs.items} suiteNames={suiteNames} />
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 sm:px-5">
        <p className="text-[12px] text-text-3">
          {runs.total === 0 ? "0 runs" : `${offset + 1}–${offset + runs.items.length} of ${runs.total}`}
        </p>
        <div className="flex items-center gap-2">
          <a href={runsCsvUrl({ mode: filters.mode, language: filters.language, scenario_name: filters.scenario, suite_id: filters.suite_id })} className={buttonClass("ghost", "sm")} download>
            <Download aria-hidden="true" className="size-3.5" />
            CSV
          </a>
          <Link
            href={pageLink(Math.max(0, offset - PAGE))}
            aria-disabled={offset === 0}
            className={cx(buttonClass("secondary", "sm"), offset === 0 && "pointer-events-none opacity-40")}
          >
            <ChevronLeft aria-hidden="true" className="size-3.5" />
            Newer
          </Link>
          <Link
            href={pageLink(offset + PAGE)}
            aria-disabled={offset + PAGE >= runs.total}
            className={cx(buttonClass("secondary", "sm"), offset + PAGE >= runs.total && "pointer-events-none opacity-40")}
          >
            Older
            <ChevronRight aria-hidden="true" className="size-3.5" />
          </Link>
        </div>
      </div>
    </Panel>
  );
}

function FilterSelect({ name, label, value, options }: { name: string; label: string; value?: string; options: readonly (readonly [string, string])[] }) {
  return (
    <label>
      <span className="text-[12px] font-medium text-text-3">{label}</span>
      <Select name={name} defaultValue={value ?? ""} className="mt-1">
        <option value="">Any</option>
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </Select>
    </label>
  );
}
