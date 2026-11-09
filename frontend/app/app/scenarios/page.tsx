import Link from "next/link";
import { Suspense } from "react";

import { PageBody, PageHeader } from "@/components/shell/page-header";
import { TableSkeleton } from "@/components/ui/loading";
import {
  EmptyState,
  ErrorState,
  Panel,
  TableScroll,
  Td,
  Th,
  buttonClass,
} from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import { formatTimestampShort, langAttr } from "@/lib/format";
import type {
  LanguageCatalogue,
  Page as PageEnvelope,
  ScenarioSummary,
} from "@/lib/api/types";

export const metadata = { title: "Scenarios" };

type SearchParams = Record<string, string | string[] | undefined>;

function one(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value || undefined;
}

export default function ScenariosPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  return (
    <>
      <PageHeader
        title="Scenarios"
        description="What a caller is trying to achieve, in which language, under what conditions. A run executes one of these."
      />
      <PageBody>
        <Suspense fallback={<TableSkeleton />}>
          <Library searchParams={searchParams} />
        </Suspense>
      </PageBody>
    </>
  );
}

async function Library({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const language = one(params.language);
  const search = one(params.q);

  let scenarios: PageEnvelope<ScenarioSummary> | null = null;
  let languages: LanguageCatalogue | null = null;
  let failure: string | null = null;

  try {
    [scenarios, languages] = await Promise.all([
      api.scenarios({
        cache: "no-store",
        // `name`, as the search endpoint declares it. A misspelled filter
        // is not rejected - it is ignored, and the page would quietly show
        // every scenario while appearing to have searched.
        query: { limit: 100, language, name: search },
      }),
      api.languages({ revalidate: 3600 }),
    ]);
  } catch (error) {
    failure =
      error instanceof ApiError ? error.message : "The library could not be loaded.";
  }

  const byCode = new Map(
    (languages?.languages ?? []).map((entry) => [entry.code, entry]),
  );

  return (
    <>
        {languages ? (
          <form
            className="flex flex-wrap items-end gap-3 rounded-lg border border-line bg-surface p-3 sm:p-4"
            aria-label="Filter scenarios"
          >
            <div className="min-w-[12rem] flex-1">
              <label
                className="block text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted"
                htmlFor="q"
              >
                Name
              </label>
              <input
                id="q"
                name="q"
                type="search"
                defaultValue={search ?? ""}
                placeholder="Search by name"
                className="mt-1 h-9 w-full rounded-md border border-line-strong bg-surface-raised px-2.5 text-[13px] text-text placeholder:text-text-muted hover:border-[#3b4756] focus-visible:border-accent"
              />
            </div>
            <div className="min-w-[10rem]">
              <label
                className="block text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted"
                htmlFor="language"
              >
                Language
              </label>
              <select
                id="language"
                name="language"
                defaultValue={language ?? ""}
                className="mt-1 h-9 w-full rounded-md border border-line-strong bg-surface-raised px-2.5 text-[13px] text-text hover:border-[#3b4756] focus-visible:border-accent"
              >
                <option value="">Any language</option>
                {languages.languages.map((entry) => (
                  <option key={entry.code} value={entry.code}>
                    {entry.name} ({entry.code})
                  </option>
                ))}
              </select>
            </div>
            <button type="submit" className={buttonClass("default", "sm")}>
              Apply
            </button>
            {language || search ? (
              <Link href="/app/scenarios" className={buttonClass("quiet", "sm")}>
                Clear
              </Link>
            ) : null}
          </form>
        ) : null}

        <Panel>
          {failure !== null || scenarios === null ? (
            <ErrorState title="The scenario library could not be loaded" detail={failure} />
          ) : scenarios.items.length === 0 ? (
            <EmptyState title={language || search ? "No scenarios match" : "No scenarios yet"}>
              {language || search ? (
                "Nothing in the library matches these filters."
              ) : (
                <>
                  Scenarios are authored as YAML and loaded through the API or
                  the <code className="font-mono text-[12px]">bhashabench</code>{" "}
                  CLI. The repository ships six reference scenarios under{" "}
                  <code className="font-mono text-[12px]">scenarios/</code>.
                </>
              )}
            </EmptyState>
          ) : (
            <>
              <TableScroll>
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="border-b border-line bg-surface-inset">
                      <Th>Name</Th>
                      <Th>Language</Th>
                      <Th>Script</Th>
                      <Th>Description</Th>
                      <Th>Updated</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {scenarios.items.map((scenario) => {
                      const meta = byCode.get(scenario.language);
                      return (
                        <tr
                          key={scenario.id}
                          className="border-b border-line transition-colors last:border-0 hover:bg-surface-raised"
                        >
                          <Td className="max-w-[20rem]">
                            <span className="block truncate font-medium text-text">
                              {scenario.name}
                            </span>
                            <span className="font-mono text-[11px] text-text-muted">
                              {scenario.id.slice(0, 8)}
                            </span>
                          </Td>
                          <Td>
                            <span className="flex flex-col">
                              <span className="font-mono text-[12px] text-text">
                                {scenario.language}
                              </span>
                              {meta ? (
                                <span
                                  className="text-[12px] text-text-muted"
                                  lang={langAttr(meta.code)}
                                >
                                  {meta.endonym}
                                </span>
                              ) : null}
                            </span>
                          </Td>
                          <Td className="font-mono text-[12px]">{meta?.script ?? "—"}</Td>
                          <Td className="max-w-[26rem]">
                            <span className="block truncate">
                              {scenario.description ?? "—"}
                            </span>
                          </Td>
                          <Td className="whitespace-nowrap font-mono text-[12px] text-text-muted">
                            {formatTimestampShort(scenario.updated_at) ?? "—"}
                          </Td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableScroll>
              <p className="border-t border-line px-4 py-3 text-[12px] text-text-muted">
                {scenarios.total} scenario{scenarios.total === 1 ? "" : "s"}
              </p>
            </>
          )}
        </Panel>
    </>
  );
}
