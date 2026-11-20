/**
 * Who the caller is and where they are, for server components.
 *
 * One read of `/auth/me`, the workspaces and each workspace's projects per
 * request, deduplicated with React's `cache()` so the layout and the page do
 * not each fetch it. Roles here only decide which controls are shown; the
 * API checks every action again.
 *
 * The selected workspace is a preference cookie (`bb_workspace`), not an
 * authorisation: it picks which workspace the settings and project pages
 * open on. Listings elsewhere span every workspace the caller belongs to, as
 * the API scopes them.
 */

import "server-only";

import { cookies } from "next/headers";
import { cache } from "react";

import { api } from "./client";
import { sessionHeaders } from "./server";
import type { Me, ProjectRead, Role, WorkspaceRead } from "./types";

export const WORKSPACE_COOKIE = "bb_workspace";

export interface ProjectInContext extends ProjectRead {
  workspace_name: string;
  role: Role;
}

export interface Context {
  auth: Record<string, string>;
  me: Me;
  workspaces: WorkspaceRead[];
  projects: ProjectInContext[];
  /** The workspace the preference cookie names, else the first. Null when none. */
  current: WorkspaceRead | null;
}

export const loadContext = cache(async (): Promise<Context> => {
  const auth = await sessionHeaders();
  const [me, workspaces] = await Promise.all([
    api.me({ cache: "no-store", headers: auth }),
    api.workspaces({ cache: "no-store", headers: auth }),
  ]);
  const perWorkspace = await Promise.all(
    workspaces.map((workspace) =>
      api
        .projects(workspace.id, { cache: "no-store", headers: auth })
        .then((projects) =>
          projects.map((project) => ({ ...project, workspace_name: workspace.name, role: workspace.role })),
        ),
    ),
  );
  const store = await cookies();
  const preferred = store.get(WORKSPACE_COOKIE)?.value;
  const current = workspaces.find((w) => w.id === preferred) ?? workspaces[0] ?? null;
  return { auth, me, workspaces, projects: perWorkspace.flat(), current };
});

const RANK: Record<Role, number> = { viewer: 0, member: 1, admin: 2, owner: 3 };

/** Mirrors backend/app/auth/permissions.py: edit needs member, manage needs admin. */
export function can(role: Role | null | undefined, action: "edit" | "manage"): boolean {
  if (!role) return false;
  return RANK[role] >= (action === "edit" ? RANK.member : RANK.admin);
}

export function projectOf(context: Context, projectId: string): ProjectInContext | null {
  return context.projects.find((project) => project.id === projectId) ?? null;
}
