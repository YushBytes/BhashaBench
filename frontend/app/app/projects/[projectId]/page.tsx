import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ArrowRight, Layers } from "lucide-react";

import { ProjectSettings } from "@/components/domain/project-controls";
import { RunsTable } from "@/components/domain/runs-table";
import { PageBody, PageHeader } from "@/components/shell/page";
import {
  ButtonLink,
  DetailSkeleton,
  EmptyState,
  ErrorState,
  Fact,
  Panel,
  PanelBody,
  PanelHeader,
} from "@/components/ui/primitives";
import { Badge } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import { can, loadContext, projectOf, type Context } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { Page, RunSummary, SuiteSummary } from "@/lib/api/types";
import { formatTimestamp, formatTimestampShort } from "@/lib/format";

export const metadata = { title: "Project" };

export default function ProjectPage({ params }: { params: Promise<{ projectId: string }> }) {
  return (
    <Suspense
      fallback={
        <>
          <PageHeader title="Project" crumbs={[{ href: "/app/projects", label: "Projects" }]} />
          <PageBody>
            <DetailSkeleton />
          </PageBody>
        </>
      }
    >
      <Project params={params} />
    </Suspense>
  );
}

async function Project({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  let context: Context;
  let suites: Page<SuiteSummary>;
  let runs: RunSummary[];
  try {
    context = await loadContext();
    if (!projectOf(context, projectId)) notFound();
    suites = await api.suites({ cache: "no-store", headers: context.auth, query: { project_id: projectId } });
    // The runs listing filters by one suite at a time; a project's activity is
    // the newest runs across its first ten suites.
    const perSuite = await Promise.all(
      suites.items
        .slice(0, 10)
        .map((s) => api.runs({ cache: "no-store", headers: context.auth, query: { suite_id: s.id, limit: 8 } }).then((p) => p.items)),
    );
    runs = perSuite
      .flat()
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .slice(0, 8);
  } catch (error) {
    signInAgainIfExpired(error);
    if (!(error instanceof ApiError)) throw error;
    return (
      <>
        <PageHeader title="Project" crumbs={[{ href: "/app/projects", label: "Projects" }]} />
        <PageBody>
          <Panel>
            <ErrorState title="This project could not be loaded" detail={error.message} />
          </Panel>
        </PageBody>
      </>
    );
  }
  const project = projectOf(context, projectId)!;
  const manage = can(project.role, "manage");
  const suiteNames = new Map(suites.items.map((s) => [s.id, s.name]));

  return (
    <>
      <PageHeader
        crumbs={[{ href: "/app/projects", label: "Projects" }, { label: project.workspace_name }, { label: project.name }]}
        title={project.name}
        description={project.description ?? undefined}
        meta={<Badge tone="idle">Your role: {project.role}</Badge>}
        actions={
          <>
            {can(project.role, "edit") ? (
              <ButtonLink href={`/app/suites?create=1&project=${project.id}`} tone="secondary">
                New suite
              </ButtonLink>
            ) : null}
            <ButtonLink href="/app/runs/new" tone="primary">
              New test run
            </ButtonLink>
          </>
        }
      />
      <PageBody>
        <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-6">
            <Panel>
              <PanelHeader title="Test suites" description={`${suites.total} in this project`} />
              {suites.items.length === 0 ? (
                <EmptyState
                  title="No suites yet"
                  icon={<Layers aria-hidden="true" className="size-5" />}
                  action={
                    can(project.role, "edit") ? (
                      <ButtonLink href={`/app/suites?create=1&project=${project.id}`} tone="primary">
                        Create a suite
                      </ButtonLink>
                    ) : null
                  }
                >
                  A suite groups scenarios you run together, such as a release check.
                </EmptyState>
              ) : (
                <ul className="divide-y divide-line">
                  {suites.items.map((suite) => (
                    <li key={suite.id}>
                      <Link
                        href={`/app/suites/${suite.id}`}
                        className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-bg-soft sm:px-5"
                      >
                        <Layers aria-hidden="true" className="size-4 shrink-0 text-text-3" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[14px] font-medium text-text group-hover:text-accent">{suite.name}</span>
                          <span className="block truncate text-[12px] text-text-3">
                            {suite.description ?? `Updated ${formatTimestampShort(suite.updated_at)}`}
                          </span>
                        </span>
                        <ArrowRight aria-hidden="true" className="size-4 text-text-3" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel>
              <PanelHeader title="Recent activity" description="The newest runs across this project's suites." />
              {runs.length === 0 ? (
                <EmptyState title="No runs in this project yet">Runs of any scenario in these suites appear here.</EmptyState>
              ) : (
                <RunsTable runs={runs} suiteNames={suiteNames} compact />
              )}
            </Panel>
          </div>

          <div className="min-w-0 space-y-6">
            <Panel>
              <PanelHeader title="Details" />
              <PanelBody>
                <dl className="grid gap-4">
                  <Fact label="Workspace">{project.workspace_name}</Fact>
                  <Fact label="Created">{formatTimestamp(project.created_at)}</Fact>
                  <Fact label="Project id" mono>
                    {project.id}
                  </Fact>
                </dl>
              </PanelBody>
            </Panel>
            <Panel>
              <PanelHeader title="Project settings" description={manage ? undefined : "Admins and owners can rename or delete a project."} />
              <PanelBody>
                {manage ? (
                  <ProjectSettings id={project.id} name={project.name} description={project.description} />
                ) : (
                  <p className="text-[13px] text-text-3">Your role here is {project.role}, so these settings are read-only to you.</p>
                )}
              </PanelBody>
            </Panel>
          </div>
        </div>
      </PageBody>
    </>
  );
}
