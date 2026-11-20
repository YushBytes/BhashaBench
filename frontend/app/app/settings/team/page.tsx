import { Suspense } from "react";
import { Check, Minus } from "lucide-react";

import { SettingsNav } from "@/components/settings/settings-nav";
import { AddMember, MemberControls } from "@/components/settings/team-controls";
import { PageBody, PageHeader } from "@/components/shell/page";
import { ErrorState, Panel, PanelBody, PanelFooter, PanelHeader, Table, TableScroll, TableSkeleton, Td, Th } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import { can, loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { MemberRead, Role } from "@/lib/api/types";

export const metadata = { title: "Team and roles" };

export default function TeamPage() {
  return (
    <>
      <PageHeader title="Settings" description="The workspace you are working in, the people in it, and your own account." />
      <PageBody>
        <SettingsNav current="/app/settings/team" />
        <Suspense fallback={<TableSkeleton rows={4} />}>
          <Team />
        </Suspense>
        <RoleMatrix />
      </PageBody>
    </>
  );
}

const PRIVILEGED = new Set<Role>(["owner", "admin"]);

async function Team() {
  let context;
  let members: MemberRead[] = [];
  try {
    context = await loadContext();
    if (context.current) members = await api.members(context.current.id, { cache: "no-store", headers: context.auth });
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="Members could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }
  const w = context.current;
  if (!w) {
    return (
      <Panel>
        <PanelBody>
          <p className="text-[14px] text-text-2">You are not in any workspace.</p>
        </PanelBody>
      </Panel>
    );
  }
  const manage = can(w.role, "manage");
  const isOwner = w.role === "owner";

  return (
    <Panel>
      <PanelHeader
        title={`Members of ${w.name}`}
        description={`${members.length} member${members.length === 1 ? "" : "s"}. Your role: ${w.role}.`}
      />
      <TableScroll label="Members">
        <Table className="min-w-[36rem]">
          <thead>
            <tr>
              <Th>Member</Th>
              <Th>Role</Th>
              <Th className="text-right">
                <span className="sr-only">Actions</span>
              </Th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => {
              const self = m.user_id === context.me.user.id;
              // An admin may not touch owners or other admins; the server enforces it too.
              const editable = manage && !self && (isOwner || !PRIVILEGED.has(m.role));
              return (
                <tr key={m.user_id}>
                  <Td>
                    <span className="block font-medium text-text">
                      {m.display_name}
                      {self ? <span className="ml-2 text-[12px] font-normal text-text-3">(you)</span> : null}
                    </span>
                    <span className="font-mono text-[12px] text-text-3">{m.email}</span>
                  </Td>
                  <Td>
                    <Badge tone={m.role === "owner" ? "ink" : "idle"}>{m.role}</Badge>
                  </Td>
                  <Td className="text-right">
                    <MemberControls
                      workspaceId={w.id}
                      userId={m.user_id}
                      name={m.display_name}
                      role={m.role}
                      isSelf={self}
                      editable={editable}
                      canGrantPrivileged={isOwner}
                    />
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      </TableScroll>
      {manage ? (
        <div className="border-t border-line px-4 py-4 sm:px-5">
          <AddMember workspaceId={w.id} canGrantPrivileged={isOwner} />
        </div>
      ) : (
        <PanelFooter>Admins and owners add and remove members. You can leave the workspace yourself.</PanelFooter>
      )}
    </Panel>
  );
}

/** Quoted from docs/AUTH.md, "Permission | Least role | Covers". */
const PERMISSIONS: { label: string; covers: string; least: Role }[] = [
  { label: "View", covers: "Read suites, scenarios, runs, turns, audio, evaluations, reports, members and projects.", least: "viewer" },
  { label: "Edit", covers: "Create and change suites and scenarios; create, start, drive and cancel runs; evaluate; record references.", least: "member" },
  { label: "Delete", covers: "Delete suites, scenarios and finished runs.", least: "admin" },
  { label: "Manage projects", covers: "Create, rename and delete projects.", least: "admin" },
  { label: "Manage members", covers: "Add, change and remove members. An admin only at member and viewer; only an owner grants, changes or removes admin and owner.", least: "admin" },
];
const ROLES: Role[] = ["viewer", "member", "admin", "owner"];
const RANK: Record<Role, number> = { viewer: 0, member: 1, admin: 2, owner: 3 };

function RoleMatrix() {
  return (
    <Panel>
      <PanelHeader title="Roles and permissions" description="Each role includes everything below it. A workspace always keeps an owner, and anyone may leave subject to that." />
      <TableScroll label="Roles and permissions">
        <Table className="min-w-[44rem]">
          <thead>
            <tr>
              <Th>Permission</Th>
              {ROLES.map((r) => (
                <Th key={r} className="text-center capitalize">
                  {r}
                </Th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PERMISSIONS.map((p) => (
              <tr key={p.label}>
                <Td>
                  <span className="block font-medium text-text">{p.label}</span>
                  <span className="text-[12px] leading-relaxed text-text-3">{p.covers}</span>
                </Td>
                {ROLES.map((r) => (
                  <Td key={r} className="text-center">
                    {RANK[r] >= RANK[p.least] ? (
                      <Check aria-label="Allowed" className="mx-auto size-4 text-ok" />
                    ) : (
                      <Minus aria-label="Not allowed" className="mx-auto size-4 text-text-3" />
                    )}
                  </Td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
      </TableScroll>
    </Panel>
  );
}
