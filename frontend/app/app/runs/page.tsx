import Link from "next/link";
import { Suspense } from "react";

import { RunFilters } from "@/components/domain/run-filters";
import { RunsTable } from "@/components/domain/runs-table";
import { TableSkeleton } from "@/components/ui/loading";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import {
  EmptyState,
  ErrorState,
  LinkButton,
  Panel,
  buttonClass,
  cx,
} from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import type { Page as PageEnvelope, RunSummary } from "@/lib/api/types";

export const metadata = { title: "Test runs" };

const PAGE_SIZE = 25;

/** Only parameters the API accepts are forwarded. Anything else is dropped
 *  rather than passed through to produce a 422. */
const FILTER_KEYS = ["status", "mode", "language", "outcome", "scenario"] as const;

type SearchParams = Record<string, string | string[] | undefined>;

function one(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value || undefined;
}

export default function RunsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  return (
    <>
      <PageHeader
        title="Test runs"
        description="Every run this server has recorded, newest first. A run's mode says how much of the system it exercised; its outcome says what it found."
        actions={
          <LinkButton href="/app/new-test" tone="primary" size="sm">
            New test
          </LinkButton>
        }
      />
      <PageBody>
        <Suspense fallback={<TableSkeleton />}>
          <RunHistory searchParams={searchParams} />
        </Suspense>
      </PageBody>
    </>
  );
}

/** Reads `searchParams` and the API, so it is suspended. */
async function RunHistory({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const offset = Number.parseInt(one(params.offset) ?? "0", 10) || 0;

  const filters: Record<string, string | undefined> = {};
  for (const key of FILTER_KEYS) filters[key] = one(params[key]);
  const active = Object.values(filters).filter(Boolean).length;

  let runs: PageEnvelope<RunSummary> | null = null;
  let failure: string | null = null;
  try {
    runs = await api.runs({
      cache: "no-store",
      query: { ...filters, limit: PAGE_SIZE, offset },
    });
  } catch (error) {
    failure =
      error instanceof ApiError
        ? error.message
        : "The run history could not be loaded.";
  }

  return (
    <>
        <RunFilters current={filters} />

        <Panel>
          {failure !== null ? (
            <ErrorState
              title="The run history could not be loaded"
              detail={failure}
            />
          ) : runs === null || runs.items.length === 0 ? (
            active > 0 ? (
              <EmptyState
                title="No runs match these filters"
                action={
                  <Link href="/app/runs" className={buttonClass("default", "sm")}>
                    Clear filters
                  </Link>
                }
              >
                {runs?.total === 0
                  ? "No run on this server matches every filter applied."
                  : "Try widening the search."}
              </EmptyState>
            ) : (
              <EmptyState
                title="No runs recorded yet"
                action={
                  <LinkButton href="/app/new-test" tone="primary" size="sm">
                    Configure the first run
                  </LinkButton>
                }
              >
                This table fills from the pipeline, not from samples. Start a
                run and its conversation, audio artefacts and stage timings
                become inspectable here.
              </EmptyState>
            )
          ) : (
            <>
              <RunsTable runs={runs.items} />
              <Pager total={runs.total} limit={runs.limit} offset={runs.offset} params={params} />
            </>
          )}
        </Panel>
    </>
  );
}

function Pager({
  total,
  limit,
  offset,
  params,
}: {
  total: number;
  limit: number;
  offset: number;
  params: SearchParams;
}) {
  const from = offset + 1;
  const to = Math.min(offset + limit, total);
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  const href = (next: number) => {
    const query = new URLSearchParams();
    for (const key of FILTER_KEYS) {
      const value = one(params[key]);
      if (value) query.set(key, value);
    }
    if (next > 0) query.set("offset", String(next));
    const qs = query.toString();
    return qs ? `/app/runs?${qs}` : "/app/runs";
  };

  if (total <= limit) {
    return (
      <p className="border-t border-line px-4 py-3 text-[12px] text-text-muted">
        {total} run{total === 1 ? "" : "s"}
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3">
      <p className="font-mono text-[12px] tabular text-text-muted">
        {from}–{to} of {total}
      </p>
      <div className="flex items-center gap-2">
        <PagerLink href={href(Math.max(0, offset - limit))} disabled={!hasPrev}>
          Previous
        </PagerLink>
        <PagerLink href={href(offset + limit)} disabled={!hasNext}>
          Next
        </PagerLink>
      </div>
    </div>
  );
}

function PagerLink({
  href,
  disabled,
  children,
}: {
  href: string;
  disabled: boolean;
  children: React.ReactNode;
}) {
  if (disabled) {
    return (
      <span
        aria-disabled="true"
        className={cx(buttonClass("default", "sm"), "cursor-not-allowed opacity-50")}
      >
        {children}
      </span>
    );
  }
  return (
    <Link href={href} className={buttonClass("default", "sm")}>
      {children}
    </Link>
  );
}
