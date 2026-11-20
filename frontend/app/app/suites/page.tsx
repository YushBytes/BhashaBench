import Link from "next/link";
import { Suspense } from "react";
import { Layers, ListChecks } from "lucide-react";

import { CreateSuiteButton, SuiteActions } from "@/components/domain/suite-controls";
import { PageBody, PageHeader } from "@/components/shell/page";
import { EmptyState, ErrorState, Panel, PanelHeader, TableSkeleton } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import { can, loadContext, projectOf, type Context } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { SuiteRead } from "@/lib/api/types";
import { formatTimestampShort } from "@/lib/format";

export const metadata = { title: "Test suites" };

export default function SuitesPage() {
  return (
    <>
      <PageHeader
        title="Test suites"
        description="Groups of scenarios you run together: a release check, one bot's regression set, one language. Each suite lives in a project."
      />
      <PageBody>
        <Suspense fallback={<TableSkeleton />}>
          <Suites />
        </Suspense>
      </PageBody>
    </>
  );
}

async function Suites() {
  let context: Context;
  let suites: SuiteRead[];
  try {
    context = await loadContext();
    const page = await api.suites({ cache: "no-store", headers: context.auth, query: { limit: 100 } });
    // Only the detail route carries a scenario count.
    suites = await Promise.all(page.items.map((s) => api.suite(s.id, { cache: "no-store", headers: context.auth })));
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="Suites could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }

  const editable = context.projects
    .filter((p) => can(p.role, "edit"))
    .map((p) => ({ id: p.id, label: context.workspaces.length > 1 ? `${p.workspace_name} / ${p.name}` : p.name }));
  const byProject = new Map<string, SuiteRead[]>();
  for (const suite of suites) byProject.set(suite.project_id, [...(byProject.get(suite.project_id) ?? []), suite]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-text-3">
          {suites.length} suite{suites.length === 1 ? "" : "s"} · {suites.reduce((n, s) => n + s.scenario_count, 0)} scenarios
        </p>
        {editable.length > 0 ? <CreateSuiteButton projects={editable} /> : <p className="text-[13px] text-text-3">Viewers cannot create suites.</p>}
      </div>

      {suites.length === 0 ? (
        <Panel>
          <EmptyState title="No suites yet" icon={<Layers aria-hidden="true" className="size-5" />}>
            Create a suite, then add scenarios to it from the reference library or the scenario builder.
          </EmptyState>
        </Panel>
      ) : (
        [...byProject.entries()].map(([projectId, items]) => {
          const project = projectOf(context, projectId);
          return (
            <Panel key={projectId}>
              <PanelHeader
                title={project ? project.name : "Project"}
                description={project ? `${project.workspace_name} · your role: ${project.role}` : undefined}
              />
              <ul className="divide-y divide-line">
                {items.map((suite) => (
                  <li key={suite.id} className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:px-5">
                    <Link href={`/app/suites/${suite.id}`} className="group flex min-w-0 flex-1 items-center gap-3">
                      <span className="flex size-9 shrink-0 items-center justify-center rounded-md border border-line bg-bg-soft">
                        <Layers aria-hidden="true" className="size-4 text-text-2" strokeWidth={1.75} />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-[14px] font-medium text-text group-hover:text-accent">{suite.name}</span>
                        <span className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[12px] text-text-3">
                          <span className="inline-flex items-center gap-1">
                            <ListChecks aria-hidden="true" className="size-3.5" />
                            {suite.scenario_count} scenario{suite.scenario_count === 1 ? "" : "s"}
                          </span>
                          <span>Updated {formatTimestampShort(suite.updated_at)}</span>
                        </span>
                      </span>
                    </Link>
                    <SuiteActions id={suite.id} name={suite.name} canEdit={can(project?.role, "edit")} />
                  </li>
                ))}
              </ul>
            </Panel>
          );
        })
      )}
    </div>
  );
}
