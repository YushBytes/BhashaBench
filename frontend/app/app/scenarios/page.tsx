import Link from "next/link";
import { Suspense } from "react";
import { BookMarked, ListChecks, Plus, Search } from "lucide-react";

import { PageBody, PageHeader } from "@/components/shell/page";
import { Input, Select } from "@/components/ui/field";
import {
  ButtonLink,
  EmptyState,
  ErrorState,
  Panel,
  PanelHeader,
  Table,
  TableScroll,
  TableSkeleton,
  Td,
  Th,
  buttonClass,
} from "@/components/ui/primitives";
import { Badge } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import { loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { LanguageCatalogue, LibraryScenario, Page, ScenarioSummary, SuiteSummary } from "@/lib/api/types";
import { formatTimestampShort, langAttr } from "@/lib/format";

export const metadata = { title: "Scenarios" };

type SearchParams = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) || undefined;

export default function ScenariosPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return (
    <>
      <PageHeader
        title="Scenarios"
        description="Who calls, in which language, what they want and under what conditions. A test run executes one scenario."
        actions={
          <ButtonLink href="/app/scenarios/new" tone="primary">
            <Plus aria-hidden="true" className="size-4" />
            New scenario
          </ButtonLink>
        }
      />
      <PageBody>
        <Suspense fallback={<TableSkeleton />}>
          <Library searchParams={searchParams} />
        </Suspense>
        <Suspense fallback={<TableSkeleton rows={3} />}>
          <Reference />
        </Suspense>
      </PageBody>
    </>
  );
}

async function Library({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const name = one(params.q);
  const language = one(params.language);
  const tag = one(params.tag);
  const archived = one(params.archived) === "1";
  let scenarios: Page<ScenarioSummary>;
  let languages: LanguageCatalogue;
  let suites: SuiteSummary[];
  try {
    const { auth } = await loadContext();
    [scenarios, languages, suites] = await Promise.all([
      // `name`, `language`, `tag`, `include_archived`: the parameters the
      // search endpoint declares. A misspelt one would be ignored, not refused.
      api.scenarios({ cache: "no-store", headers: auth, query: { limit: 100, name, language, tag, include_archived: archived || undefined } }),
      api.languages({ revalidate: 3600 }),
      api.suites({ cache: "no-store", headers: auth }).then((p) => p.items),
    ]);
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="Scenarios could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }
  const byCode = new Map(languages.languages.map((l) => [l.code, l]));
  const suiteName = new Map(suites.map((s) => [s.id, s.name]));
  const filtered = Boolean(name || language || tag || archived);

  return (
    <Panel>
      <form className="flex flex-col gap-3 border-b border-line p-4 sm:flex-row sm:flex-wrap sm:items-end sm:px-5" aria-label="Filter scenarios">
        <label className="min-w-0 flex-1 sm:min-w-[14rem]">
          <span className="text-[12px] font-medium text-text-3">Name</span>
          <span className="relative mt-1 block">
            <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-text-3" />
            <Input name="q" type="search" defaultValue={name ?? ""} placeholder="Search by name" className="pl-8" />
          </span>
        </label>
        <label className="sm:w-56">
          <span className="text-[12px] font-medium text-text-3">Language</span>
          <Select name="language" defaultValue={language ?? ""} className="mt-1">
            <option value="">Any language</option>
            {languages.languages.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name} ({l.code})
              </option>
            ))}
          </Select>
        </label>
        <label className="sm:w-40">
          <span className="text-[12px] font-medium text-text-3">Tag</span>
          <Input name="tag" defaultValue={tag ?? ""} placeholder="e.g. smoke" className="mt-1" />
        </label>
        <label className="flex h-9 items-center gap-2 text-[13px] text-text-2">
          <input type="checkbox" name="archived" value="1" defaultChecked={archived} className="size-4" />
          Include archived
        </label>
        <div className="flex gap-2">
          <button type="submit" className={buttonClass("secondary", "md")}>
            Apply
          </button>
          {filtered ? (
            <Link href="/app/scenarios" className={buttonClass("ghost", "md")}>
              Clear
            </Link>
          ) : null}
        </div>
      </form>

      {scenarios.items.length === 0 ? (
        <EmptyState
          title={filtered ? "No scenarios match" : "No scenarios yet"}
          icon={<ListChecks aria-hidden="true" className="size-5" />}
          action={
            filtered ? null : (
              <ButtonLink href="/app/scenarios/new" tone="primary">
                Build a scenario
              </ButtonLink>
            )
          }
        >
          {filtered ? "Nothing matches these filters." : "Build one in the guided editor, or start from a reference scenario below."}
        </EmptyState>
      ) : (
        <>
          <TableScroll label="Scenarios">
            <Table className="min-w-[48rem]">
              <thead>
                <tr>
                  <Th>Scenario</Th>
                  <Th>Language</Th>
                  <Th>Suite</Th>
                  <Th>Updated</Th>
                </tr>
              </thead>
              <tbody>
                {scenarios.items.map((scenario) => {
                  const meta = byCode.get(scenario.language);
                  return (
                    <tr key={scenario.id} className="hover:bg-bg-soft">
                      <Td className="max-w-[26rem]">
                        <Link href={`/app/scenarios/${scenario.id}`} className="block truncate font-medium text-text hover:text-accent">
                          {scenario.name}
                        </Link>
                        <span className="mt-0.5 block truncate text-[12px] text-text-3">
                          {scenario.archived_at ? <span className="font-medium text-warn">Archived · </span> : null}
                          {scenario.description ?? "No description"}
                        </span>
                      </Td>
                      <Td>
                        <span className="block font-mono text-[12px] text-text">{scenario.language}</span>
                        {meta ? (
                          <span lang={langAttr(meta.code)} className="text-[12px] text-text-3">
                            {meta.endonym} · {meta.script}
                          </span>
                        ) : null}
                      </Td>
                      <Td>
                        <Link href={`/app/suites/${scenario.suite_id}`} className="text-[13px] text-text-2 hover:text-accent">
                          {suiteName.get(scenario.suite_id) ?? scenario.suite_id.slice(0, 8)}
                        </Link>
                      </Td>
                      <Td className="whitespace-nowrap font-mono text-[12px] text-text-3">{formatTimestampShort(scenario.updated_at)}</Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          </TableScroll>
          <p className="border-t border-line px-4 py-3 text-[12px] text-text-3 sm:px-5">
            {scenarios.total} scenario{scenarios.total === 1 ? "" : "s"}
            {scenarios.total > scenarios.items.length ? `, showing the first ${scenarios.items.length}` : ""}
          </p>
        </>
      )}
    </Panel>
  );
}

/** The scenarios that ship with BhashaBench, as starting templates. */
async function Reference() {
  let library: LibraryScenario[];
  try {
    const { auth } = await loadContext();
    library = (await api.scenarioLibrary({ cache: "no-store", headers: auth })).scenarios;
  } catch {
    return null;
  }
  if (library.length === 0) return null;
  return (
    <Panel>
      <PanelHeader
        title="Reference library"
        icon={<BookMarked aria-hidden="true" className="size-4" />}
        description="Scenarios that ship with BhashaBench, one per language plus demos. Open one in the builder, edit it, and add it to a suite."
      />
      <ul className="grid gap-px bg-line sm:grid-cols-2 xl:grid-cols-3">
        {library.map((item) => (
          <li key={item.key} className="bg-bg">
            <Link href={`/app/scenarios/new?template=${encodeURIComponent(item.key)}`} className="group flex h-full flex-col p-5 transition-colors hover:bg-bg-soft">
              <span className="flex items-start justify-between gap-2">
                <span className="font-mono text-[13px] font-medium text-text group-hover:text-accent">{item.name}</span>
                <Badge tone="idle">{item.language}</Badge>
              </span>
              <span className="mt-2 line-clamp-3 text-[13px] leading-relaxed text-text-3">{item.description ?? item.objective}</span>
              <span className="mt-auto pt-4 text-[12px] font-medium text-accent">Use as a template</span>
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
