"use client";

/**
 * Member and project controls. Each one calls its real endpoint and then
 * refreshes the server-rendered page; nothing is updated optimistically, so
 * the screen never shows a role or a project the server has not accepted.
 * The server decides who may do what (docs/AUTH.md) - these controls are
 * shown only to roles that can use them, and a refusal is shown verbatim.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, buttonClass } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import type { Role } from "@/lib/api/types";

const ROLES: Role[] = ["owner", "admin", "member", "viewer"];
const field =
  "mt-1.5 block w-full rounded-md border border-line-strong bg-surface-raised px-3 py-2 text-[13px] text-text";

function useAction() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function run(action: () => Promise<unknown>) {
    setPending(true);
    setError(null);
    try {
      await action();
      router.refresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The request failed.");
    } finally {
      setPending(false);
    }
  }
  return { error, pending, run };
}

function Failure({ error }: { error: string | null }) {
  return error === null ? null : (
    <p role="alert" className="mt-2 text-[12px] text-bad">
      {error}
    </p>
  );
}

export function AddMember({ workspaceId, canGrantPrivileged }: { workspaceId: string; canGrantPrivileged: boolean }) {
  const { error, pending, run } = useAction();
  const roles = canGrantPrivileged ? ROLES : (["member", "viewer"] as Role[]);
  return (
    <form
      className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_10rem_auto] sm:items-end"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        void run(() =>
          api.addMember(workspaceId, String(data.get("email")), String(data.get("role")) as Role),
        );
      }}
    >
      <label className="block text-[13px] font-medium text-text-muted">
        Email of an existing account
        <input name="email" type="email" required className={field} />
      </label>
      <label className="block text-[13px] font-medium text-text-muted">
        Role
        <select name="role" defaultValue="member" className={field}>
          {roles.map((role) => (
            <option key={role} value={role}>{role}</option>
          ))}
        </select>
      </label>
      <Button type="submit" tone="primary" size="sm" disabled={pending}>
        {pending ? "Adding…" : "Add member"}
      </Button>
      <div className="sm:col-span-3"><Failure error={error} /></div>
    </form>
  );
}

export function MemberRole({
  workspaceId,
  userId,
  role,
  editable,
  canGrantPrivileged,
}: {
  workspaceId: string;
  userId: string;
  role: Role;
  editable: boolean;
  canGrantPrivileged: boolean;
}) {
  const { error, pending, run } = useAction();
  if (!editable) return <span className="font-mono text-[13px]">{role}</span>;
  const roles = canGrantPrivileged ? ROLES : (["member", "viewer"] as Role[]);
  return (
    <div>
      <div className="flex items-center gap-2">
        <select
          aria-label="Role"
          defaultValue={role}
          disabled={pending}
          className="rounded-md border border-line-strong bg-surface-raised px-2 py-1 text-[13px] text-text"
          onChange={(event) => void run(() => api.changeRole(workspaceId, userId, event.target.value as Role))}
        >
          {roles.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
        <button
          type="button"
          disabled={pending}
          className={buttonClass("default", "sm")}
          onClick={() => void run(() => api.removeMember(workspaceId, userId))}
        >
          Remove
        </button>
      </div>
      <Failure error={error} />
    </div>
  );
}

export function CreateProject({ workspaceId }: { workspaceId: string }) {
  const { error, pending, run } = useAction();
  return (
    <form
      className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
      onSubmit={(event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const name = String(new FormData(form).get("name"));
        void run(async () => {
          await api.createProject(workspaceId, name);
          form.reset();
        });
      }}
    >
      <label className="block text-[13px] font-medium text-text-muted">
        New project name
        <input name="name" required maxLength={200} className={field} />
      </label>
      <Button type="submit" tone="primary" size="sm" disabled={pending}>
        {pending ? "Creating…" : "Create project"}
      </Button>
      <div className="sm:col-span-2"><Failure error={error} /></div>
    </form>
  );
}

export function CreateWorkspace() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  return (
    <form
      className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        setPending(true);
        setError(null);
        try {
          const created = await api.createWorkspace(String(new FormData(form).get("name")));
          form.reset();
          router.push(`/app/workspace?id=${created.id}`);
          router.refresh();
        } catch (cause) {
          setError(cause instanceof ApiError ? cause.message : "The workspace could not be created.");
        } finally {
          setPending(false);
        }
      }}
    >
      <label className="block text-[13px] font-medium text-text-muted">
        New workspace name (you become its owner; it gets a Default project)
        <input name="name" required maxLength={200} className={field} />
      </label>
      <Button type="submit" tone="primary" size="sm" disabled={pending}>
        {pending ? "Creating…" : "Create workspace"}
      </Button>
      {error ? <p role="alert" className="text-[12px] text-bad sm:col-span-2">{error}</p> : null}
    </form>
  );
}
