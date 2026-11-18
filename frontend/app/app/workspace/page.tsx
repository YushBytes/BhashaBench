import { Suspense } from "react";

import {
  AddMember,
  CreateProject,
  CreateWorkspace,
  MemberRole,
} from "@/components/domain/workspace-controls";
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
} from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import { sessionHeaders, signInAgainIfExpired } from "@/lib/api/server";
import type { MemberRead, Me, ProjectRead, WorkspaceRead } from "@/lib/api/types";
import { formatTimestampShort } from "@/lib/format";

export const metadata = { title: "Workspace" };

type SearchParams = Record<string, string | string[] | undefined>;

export default function WorkspacePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return (
    <>
      <PageHeader
        title="Workspace"
        description="Who can see your suites, runs and recordings, and what each of them may do. Nothing here is visible outside the workspace."
      />
      <PageBody>
        <Suspense fallback={<TableSkeleton />}>
          <Workspace searchParams={searchParams} />
        </Suspense>
      </PageBody>
    </>
  );
}

const PRIVILEGED = new Set(["owner", "admin"]);

async function Workspace({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const auth = await sessionHeaders();
  const params = await searchParams;
  let me: Me;
  let workspaces: WorkspaceRead[];
  try {
    [me, workspaces] = await Promise.all([
      api.me({ cache: "no-store", headers: auth }),
      api.workspaces({ cache: "no-store", headers: auth }),
    ]);
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="The workspace could not be loaded" detail={error instanceof ApiError ? error.message : "The request failed."} />
      </Panel>
    );
  }
  if (workspaces.length === 0) {
    return (
      <Panel>
        <EmptyState title="You are not in any workspace">
          Create one below, or ask an owner or admin of a workspace to add you by email.
        </EmptyState>
        <div className="border-t border-line p-4 sm:p-5">
          <CreateWorkspace />
        </div>
      </Panel>
    );
  }
  const requested = typeof params.id === "string" ? params.id : undefined;
  const workspace = workspaces.find((w) => w.id === requested) ?? workspaces[0];
  const canManage = PRIVILEGED.has(workspace.role);
  const isOwner = workspace.role === "owner";

  let members: MemberRead[];
  let projects: ProjectRead[];
  try {
    [members, projects] = await Promise.all([
      api.members(workspace.id, { cache: "no-store", headers: auth }),
      api.projects(workspace.id, { cache: "no-store", headers: auth }),
    ]);
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="Members could not be loaded" detail={error instanceof ApiError ? error.message : "The request failed."} />
      </Panel>
    );
  }

  return (
    <div className="grid min-w-0 gap-5">
      <Panel>
        <PanelHeader
          title={workspace.name}
          description={`Your role here: ${workspace.role}.${workspaces.length > 1 ? " You belong to other workspaces too." : ""}`}
          actions={
            workspaces.length > 1 ? (
              <nav aria-label="Workspaces" className="flex flex-wrap gap-1">
                {workspaces.map((w) => (
                  <a key={w.id} href={`/app/workspace?id=${w.id}`} aria-current={w.id === workspace.id ? "page" : undefined}
                     className="rounded-md px-2.5 py-1.5 text-[13px] text-text-muted hover:bg-surface-raised aria-[current=page]:text-text">
                    {w.name}
                  </a>
                ))}
              </nav>
            ) : null
          }
        />
        <TableScroll>
          <table className="w-full min-w-max text-left text-[13px]">
            <thead>
              <tr>
                <Th>Member</Th>
                <Th>Email</Th>
                <Th>Role</Th>
              </tr>
            </thead>
            <tbody>
              {members.map((m) => {
                const self = m.user_id === me.user.id;
                // An admin may not touch owners or other admins; the server
                // enforces this, the control just does not offer it.
                const editable = canManage && !self && (isOwner || !PRIVILEGED.has(m.role));
                return (
                  <tr key={m.user_id} className="border-t border-line align-top">
                    <Td className="font-medium text-text">{m.display_name}{self ? <span className="ml-2 text-text-dim">(you)</span> : null}</Td>
                    <Td className="font-mono">{m.email}</Td>
                    <Td>
                      <MemberRole workspaceId={workspace.id} userId={m.user_id} role={m.role} editable={editable} canGrantPrivileged={isOwner} />
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableScroll>
        {canManage ? (
          <div className="border-t border-line p-4 sm:p-5">
            <AddMember workspaceId={workspace.id} canGrantPrivileged={isOwner} />
          </div>
        ) : null}
      </Panel>

      <Panel>
        <PanelHeader title="New workspace" description="A separate tenancy boundary: nothing is shared between workspaces." />
        <div className="p-4 sm:p-5">
          <CreateWorkspace />
        </div>
      </Panel>

      <Panel>
        <PanelHeader title="Projects" description="Suites live in projects. A project holding suites cannot be deleted." />
        <TableScroll>
          <table className="w-full min-w-max text-left text-[13px]">
            <thead>
              <tr>
                <Th>Project</Th>
                <Th>Created</Th>
                <Th>Id</Th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className="border-t border-line">
                  <Td className="font-medium text-text">{p.name}</Td>
                  <Td>{formatTimestampShort(p.created_at)}</Td>
                  <Td className="font-mono text-text-dim">{p.id}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
        {canManage ? (
          <div className="border-t border-line p-4 sm:p-5">
            <CreateProject workspaceId={workspace.id} />
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
