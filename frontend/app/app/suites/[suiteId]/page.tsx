import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ListChecks, Plus } from "lucide-react";

import { RunsTable } from "@/components/domain/runs-table";
import { ExportBundleButton, ImportBundleButton, MoveScenario, SuiteActions } from "@/components/domain/suite-controls";
import { PageBody, PageHeader } from "@/components/shell/page";
import {
  ButtonLink,
  DetailSkeleton,
  EmptyState,
  ErrorState,
  Panel,
  PanelFooter,
  PanelHeader,
  Table,
  TableScroll,
  Td,
  Th,
  linkClass,
} from "@/components/ui/primitives";
import { Badge } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import { can, loadContext, projectOf, type Context } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { Page, RunSummary, ScenarioSummary, SuiteRead, SuiteSummary } from "@/lib/api/types";
import { formatTimestampShort, langAttr } from "@/lib/format";

export const metadata = { title: "Test suite" };

type SearchParams = Record<string, string | string[] | undefined>;

export default function SuitePage({ params, searchParams }: { params: Promise<{ suiteId: string }>; searchParams: Promise<SearchParams> }) {
  return (
    <Suspense
      fallback={
        <>
          <PageHeader title="Test suite" crumbs={[{ href: "/app/suites", label: "Test suites" }]} />
          <PageBody>
            <DetailSkeleton />
          </PageBody>
        </>
      }
    >
      <Suite params={params} searchParams={searchParams} />
    </Suspense>
  );
}

async function Suite({ params, searchParams }: { params: Promise<{ suiteId: string }>; searchParams: Promise<SearchParams> }) {
  const { suiteId } = await params;
  const archived = (await searchParams).archived === "1";
  let context: Context;
  let suite: SuiteRead;
  let scenarios: Page<ScenarioSummary>;
  let runs: Page<RunSummary>;
  let others: SuiteSummary[];
  try {
    context = await loadContext();
    [suite, scenarios, runs, others] = await Promise.all([
      api.suite(suiteId, { cache: "no-store", headers: context.auth }),
      api.suiteScenarios(suiteId, { cache: "no-store", headers: context.auth, query: { include_archived: archived || undefined } }),
      api.runs({ cache: "no-store", headers: context.auth, query: { suite_id: suiteId, limit: 10 } }),
      api.suites({ cache: "no-store", headers: context.auth }).then((p) => p.items.filter((s) => s.id !== suiteId)),
    ]);
  } catch (error) {
    signInAgainIfExpired(error);
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <>
        <PageHeader title="Test suite" crumbs={[{ href: "/app/suites", label: "Test suites" }]} />
        <PageBody>
          <Panel>
            <ErrorState title="This suite could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
          </Panel>
        </PageBody>
      </>
    );
  }

  const project = projectOf(context, suite.project_id);
  const edit = can(project?.role, "edit");
  // A scenario may move only to suites the caller can also edit.
  const targets = others
    .filter((s) => can(projectOf(context, s.project_id)?.role, "edit"))
    .map((s) => ({ id: s.id, label: `${projectOf(context, s.project_id)?.name ?? "Project"} / ${s.name}` }));

  return (
    <>
      <PageHeader
        crumbs={[
          { href: "/app/suites", label: "Test suites" },
          ...(project ? [{ href: `/app/projects/${project.id}`, label: project.name }] : []),
          { label: suite.name },
        ]}
        title={suite.name}
        description={suite.description ?? undefined}
        meta={
          <>
            <Badge tone="idle">
              {suite.scenario_count} scenario{suite.scenario_count === 1 ? "" : "s"}
            </Badge>
            <Badge tone="idle">{runs.total} runs</Badge>
          </>
        }
        actions={
          <>
            <ExportBundleButton suiteId={suite.id} suiteName={suite.name} />
            {edit ? <ImportBundleButton suiteId={suite.id} /> : null}
            {edit ? (
              <ButtonLink href={`/app/scenarios/new?suite=${suite.id}`} tone="primary" size="sm">
                <Plus aria-hidden="true" className="size-3.5" />
                Add scenario
              </ButtonLink>
            ) : null}
          </>
        }
      />
      <PageBody>
        <Panel>
          <PanelHeader
            title="Scenarios"
            description="Each run executes one of these. Scenarios have no order inside a suite, so there is nothing to reorder."
            actions={
              <Link href={archived ? `/app/suites/${suite.id}` : `/app/suites/${suite.id}?archived=1`} className={linkClass + " text-[13px]"}>
                {archived ? "Hide archived" : "Show archived"}
              </Link>
            }
          />
          {scenarios.items.length === 0 ? (
            <EmptyState
              title="This suite is empty"
              icon={<ListChecks aria-hidden="true" className="size-5" />}
              action={
                edit ? (
                  <ButtonLink href={`/app/scenarios/new?suite=${suite.id}`} tone="primary">
                    Add a scenario
                  </ButtonLink>
                ) : null
              }
            >
              Start from a shipped reference scenario, build one in the guided editor, or import a bundle.
            </EmptyState>
          ) : (
            <TableScroll label="Scenarios in this suite">
              <Table className="min-w-[40rem]">
                <thead>
                  <tr>
                    <Th>Scenario</Th>
                    <Th>Language</Th>
                    <Th>Updated</Th>
                    <Th className="text-right">
                      <span className="sr-only">Actions</span>
                    </Th>
                  </tr>
                </thead>
                <tbody>
                  {scenarios.items.map((scenario) => (
                    <tr key={scenario.id} className="hover:bg-bg-soft">
                      <Td className="max-w-[24rem]">
                        <Link href={`/app/scenarios/${scenario.id}`} className="block truncate font-medium text-text hover:text-accent">
                          {scenario.name}
                        </Link>
                        <span className="block truncate text-[12px] text-text-3">
                          {scenario.archived_at ? <span className="font-medium text-warn">Archived · </span> : null}
                          {scenario.description ?? "No description"}
                        </span>
                      </Td>
                      <Td className="font-mono text-[12px]">
                        <span lang={langAttr(scenario.language)}>{scenario.language}</span>
                      </Td>
                      <Td className="whitespace-nowrap font-mono text-[12px] text-text-3">{formatTimestampShort(scenario.updated_at)}</Td>
                      <Td className="text-right">
                        <span className="inline-flex flex-wrap justify-end gap-1">
                          {scenario.archived_at ? null : (
                            <ButtonLink href={`/app/runs/new?scenario=${scenario.id}`} tone="ghost" size="sm">
                              Run
                            </ButtonLink>
                          )}
                          {edit ? <MoveScenario scenarioId={scenario.id} scenarioName={scenario.name} targets={targets} /> : null}
                        </span>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </TableScroll>
          )}
          <PanelFooter>
            Runs execute one scenario at a time; there is no whole-suite run. To retire a scenario without losing its runs, archive
            it from its own page.
          </PanelFooter>
        </Panel>

        <Panel>
          <PanelHeader
            title="Run history"
            description={`${runs.total} run${runs.total === 1 ? "" : "s"} of scenarios in this suite.`}
            actions={
              runs.total > 0 ? (
                <ButtonLink href={`/app/runs?suite_id=${suite.id}`} tone="ghost" size="sm">
                  All runs
                </ButtonLink>
              ) : null
            }
          />
          {runs.items.length === 0 ? <EmptyState title="No runs yet">Run a scenario from the table above.</EmptyState> : <RunsTable runs={runs.items} compact />}
        </Panel>

        {edit ? (
          <Panel>
            <PanelHeader title="Suite settings" description="Renaming keeps every scenario and run attached." />
            <div className="px-4 py-4 sm:px-5">
              <SuiteActions id={suite.id} name={suite.name} canEdit={edit} afterDelete="/app/suites" />
            </div>
          </Panel>
        ) : null}
      </PageBody>
    </>
  );
}
