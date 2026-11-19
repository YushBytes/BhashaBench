/**
 * The caller's role in the workspace that holds a suite, for server
 * components deciding which controls to show. The server checks every
 * action again; this only avoids offering a button that will be refused.
 */

import "server-only";

import { api } from "./client";
import type { Role } from "./types";

const RANK: Record<Role, number> = { viewer: 0, member: 1, admin: 2, owner: 3 };

/** `edit` needs member, `delete` needs admin, as in backend/app/auth/permissions.py. */
export function allows(role: Role | null, action: "edit" | "delete"): boolean {
  if (role === null) return false;
  return RANK[role] >= (action === "edit" ? RANK.member : RANK.admin);
}

export async function roleForSuite(
  suiteId: string,
  headers: Record<string, string>,
): Promise<Role | null> {
  try {
    const [suites, workspaces] = await Promise.all([
      api.suites({ cache: "no-store", headers }),
      api.workspaces({ cache: "no-store", headers }),
    ]);
    const suite = suites.items.find((item) => item.id === suiteId);
    if (!suite) return null;
    for (const workspace of workspaces) {
      const projects = await api.projects(workspace.id, { cache: "no-store", headers });
      if (projects.some((project) => project.id === suite.project_id)) return workspace.role;
    }
  } catch {
    return null;
  }
  return null;
}
