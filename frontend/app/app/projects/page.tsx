import Link from "next/link";
import { Suspense } from "react";
import { FolderKanban, Layers } from "lucide-react";

import { CreateProjectButton } from "@/components/domain/project-controls";
import { PageBody, PageHeader } from "@/components/shell/page";
import { EmptyState, ErrorState, Panel, PanelHeader, TableSkeleton } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import { can, loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import { formatTimestampShort } from "@/lib/format";

export const metadata = { title: "Projects" };

export default function ProjectsPage() {
  return (
    <>
      <PageHeader
        title="Projects"
        description="A project holds the test suites for one voice bot or product. Every workspace starts with a Default project."
      />
      <PageBody>
        <Suspense fallback={<TableSkeleton rows={3} />}>
          <Projects />
        </Suspense>
      </PageBody>
    </>
  );
}

async function Projects() {
  let context;
  let suiteCounts: Map<string, number>;
  try {
    context = await loadContext();
    const auth = context.auth;
    const counts = await Promise.all(
      context.projects.map((p) =>
        api
          .suites({ cache: "no-store", headers: auth, query: { project_id: p.id, limit: 1 } })
          .then((page) => [p.id, page.total] as const),
      ),
    );
    suiteCounts = new Map(counts);
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="Projects could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }

  const manageable = context.workspaces.filter((w) => can(w.role, "manage")).map((w) => ({ id: w.id, name: w.name }));
  const currentId = context.current?.id;
  const ordered = [...context.workspaces].sort((a, b) => (a.id === currentId ? -1 : b.id === currentId ? 1 : 0));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-text-3">
          {context.projects.length} project{context.projects.length === 1 ? "" : "s"} in {context.workspaces.length} workspace
          {context.workspaces.length === 1 ? "" : "s"}
        </p>
        {manageable.length > 0 ? (
          <CreateProjectButton workspaces={manageable} />
        ) : (
          <p className="text-[13px] text-text-3">Only admins and owners create projects.</p>
        )}
      </div>

      {ordered.map((workspace) => {
        const projects = context.projects.filter((p) => p.workspace_id === workspace.id);
        return (
          <Panel key={workspace.id}>
            <PanelHeader
              title={workspace.name}
              description={`Your role: ${workspace.role}`}
              actions={workspace.id === currentId ? <Badge tone="idle">Current workspace</Badge> : null}
            />
            {projects.length === 0 ? (
              <EmptyState title="No projects in this workspace" icon={<FolderKanban aria-hidden="true" className="size-5" />}>
                {can(workspace.role, "manage") ? "Create one to start adding suites." : "An admin or owner can create one."}
              </EmptyState>
            ) : (
              <ul className="grid gap-px bg-line sm:grid-cols-2 xl:grid-cols-3">
                {projects.map((project) => (
                  <li key={project.id} className="bg-bg">
                    <Link href={`/app/projects/${project.id}`} className="group flex h-full flex-col p-5 transition-colors hover:bg-bg-soft">
                      <span className="flex items-start justify-between gap-3">
                        <span className="text-[15px] font-semibold text-text group-hover:text-accent">{project.name}</span>
                        <FolderKanban aria-hidden="true" className="size-4 shrink-0 text-text-3" strokeWidth={1.75} />
                      </span>
                      <span className="mt-1.5 line-clamp-2 text-[13px] leading-relaxed text-text-3">
                        {project.description ?? "No description."}
                      </span>
                      <span className="mt-4 flex flex-wrap items-center gap-3 text-[12px] text-text-3">
                        <span className="inline-flex items-center gap-1">
                          <Layers aria-hidden="true" className="size-3.5" />
                          {suiteCounts.get(project.id) ?? 0} suites
                        </span>
                        <span>Created {formatTimestampShort(project.created_at)}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        );
      })}

      {context.workspaces.length === 0 ? (
        <Panel>
          <EmptyState title="You are not in any workspace">Create one under Settings, or ask an owner to add you by email.</EmptyState>
        </Panel>
      ) : null}
    </div>
  );
}
