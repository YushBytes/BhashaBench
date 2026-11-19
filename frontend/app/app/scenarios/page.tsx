import Link from "next/link";
import { Suspense } from "react";

import {
  AddScenario,
  SuiteRow,
  CreateSuite,
  type ProjectChoice,
} from "@/components/domain/scenario-authoring";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { TableSkeleton } from "@/components/ui/loading";
import {
  EmptyState,
  ErrorState,
  Panel,
  PanelHeader,
  TableScroll,
  Td,
  Th,
  buttonClass,
} from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import { sessionHeaders, signInAgainIfExpired } from "@/lib/api/server";
import { formatTimestampShort, langAttr } from "@/lib/format";
import type {
  LanguageCatalogue,
  LibraryScenario,
  Page as PageEnvelope,
  ScenarioSummary,
  SuiteSummary,
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
        <Suspense fallback={<TableSkeleton rows={2} />}>
          <Authoring />
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
  const auth = await sessionHeaders();
  const params = await searchParams;
  const language = one(params.language);
  const search = one(params.q);
  const showArchived = one(params.archived) === "1";

  let scenarios: PageEnvelope<ScenarioSummary> | null = null;
  let languages: LanguageCatalogue | null = null;
  let failure: string | null = null;

  try {
    [scenarios, languages] = await Promise.all([
      api.scenarios({
        cache: "no-store",
        headers: auth,
        // `name`, as the search endpoint declares it. A misspelled filter
        // is not rejected - it is ignored, and the page would quietly show
        // every scenario while appearing to have searched.
        query: { limit: 100, language, name: search, include_archived: showArchived || undefined },
      }),
      api.languages({ revalidate: 3600 }),
    ]);
  } catch (error) {
    signInAgainIfExpired(error);
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
            <label className="flex h-9 items-center gap-2 text-[13px] text-text-dim">
              <input
                type="checkbox"
                name="archived"
                value="1"
                defaultChecked={showArchived}
                className="size-4 accent-[var(--accent)]"
              />
              Show archived
            </label>
            <button type="submit" className={buttonClass("default", "sm")}>
              Apply
            </button>
            {language || search || showArchived ? (
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
                  Create a suite below, then start from one of the shipped
                  reference scenarios or paste your own YAML. The API and the{" "}
                  <code className="font-mono text-[12px]">bhashabench</code> CLI
                  load scenarios too.
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
                            <Link
                              href={`/app/scenarios/${scenario.id}`}
                              className="block truncate font-medium text-text hover:text-accent"
                            >
                              {scenario.name}
                            </Link>
                            {scenario.archived_at ? (
                              <span className="text-[11px] text-warn">Archived · </span>
                            ) : null}
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

/** Suites and new scenarios. The page loads the caller's suites; the forms
 *  call the real create and validate routes. */
async function Authoring() {
  const auth = await sessionHeaders();
  let suites: PageEnvelope<SuiteSummary>;
  let library: LibraryScenario[] | null = null;
  const projects: ProjectChoice[] = [];
  try {
    const [loaded, workspaces, shipped] = await Promise.all([
      api.suites({ cache: "no-store", headers: auth }),
      api.workspaces({ cache: "no-store", headers: auth }),
      // The library is a convenience; the editor works without it.
      api.scenarioLibrary({ cache: "no-store", headers: auth }).catch(() => null),
    ]);
    suites = loaded;
    library = shipped?.scenarios ?? null;
    // Projects the caller may create suites in: member role or above.
    for (const workspace of workspaces.filter((w) => w.role !== "viewer")) {
      for (const project of await api.projects(workspace.id, { cache: "no-store", headers: auth })) {
        projects.push({ id: project.id, label: `${workspace.name} / ${project.name}` });
      }
    }
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState
          title="Suites could not be loaded"
          detail={error instanceof ApiError ? error.message : "The request failed."}
        />
      </Panel>
    );
  }
  return (
    <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
      <Panel>
        <PanelHeader
          title="Suites"
          description={`${suites.total} in your workspace${suites.total === 1 ? "" : "s"}. Names are unique within a project.`}
        />
        <ul className="divide-y divide-line">
          {suites.items.map((suite) => (
            <li key={suite.id} className="px-4 py-2.5 text-[13px] text-text sm:px-5">
              <SuiteRow id={suite.id} name={suite.name} canEdit={projects.some((p) => p.id === suite.project_id)} />
            </li>
          ))}
        </ul>
        <div className="border-t border-line p-4 sm:p-5">
          {projects.length > 0 ? (
            <CreateSuite projects={projects} />
          ) : (
            <p className="text-[13px] text-text-muted">
              Your role is viewer everywhere, so you cannot create suites.
            </p>
          )}
        </div>
      </Panel>
      <Panel>
        <PanelHeader title="Add a scenario" description="Validated by the server before it can be added, and again when it is." />
        <div className="p-4 sm:p-5">
          <AddScenario suites={suites.items} library={library} />
        </div>
      </Panel>
    </div>
  );
}
