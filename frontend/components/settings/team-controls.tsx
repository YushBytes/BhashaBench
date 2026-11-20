"use client";

/**
 * Member controls. Each calls its endpoint and re-reads the page; nothing is
 * updated optimistically. They are offered only where the role allows -
 * an admin manages members and viewers, only an owner grants or removes
 * admin and owner - and the server decides again, its refusal shown as
 * worded (for example, removing the last owner is a 409).
 */

import { useRouter } from "next/navigation";
import { useState } from "react";
import { UserPlus } from "lucide-react";

import { Field, Input, Select } from "@/components/ui/field";
import { ConfirmAction, failureMessage, useAction } from "@/components/ui/interactive";
import { Button, Notice } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import type { Role } from "@/lib/api/types";

const ALL: Role[] = ["owner", "admin", "member", "viewer"];

export function AddMember({ workspaceId, canGrantPrivileged }: { workspaceId: string; canGrantPrivileged: boolean }) {
  const { error, pending, run } = useAction();
  const [done, setDone] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);
  const roles = canGrantPrivileged ? ALL : (["member", "viewer"] as Role[]);
  return (
    <form
      noValidate
      className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_10rem_auto] sm:items-end"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const data = new FormData(form);
        const email = String(data.get("email") ?? "").trim();
        setDone(null);
        if (!email.includes("@")) {
          setEmailError("Enter the email address of an existing account.");
          return;
        }
        setEmailError(null);
        const added = await run(() => api.addMember(workspaceId, email, String(data.get("role")) as Role), "The member was not added.");
        if (added) {
          setDone(`Added ${added.display_name} as ${added.role}.`);
          form.reset();
        }
      }}
    >
      <Field id="member-email" label="Email of an existing account" error={emailError} hint="There are no email invitations: the person signs up first, then you add them here.">
        <Input name="email" type="email" autoComplete="off" />
      </Field>
      <Field id="member-role" label="Role">
        <Select name="role" defaultValue="member">
          {roles.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </Select>
      </Field>
      <Button type="submit" tone="primary" disabled={pending} className="sm:mb-[22px]">
        <UserPlus aria-hidden="true" className="size-4" />
        {pending ? "Adding…" : "Add member"}
      </Button>
      <div className="sm:col-span-3">
        {error ? <Notice tone="bad">{error}</Notice> : null}
        {done ? <Notice tone="ok">{done}</Notice> : null}
      </div>
    </form>
  );
}

export function MemberControls({
  workspaceId,
  userId,
  name,
  role,
  isSelf,
  editable,
  canGrantPrivileged,
}: {
  workspaceId: string;
  userId: string;
  name: string;
  role: Role;
  isSelf: boolean;
  editable: boolean;
  canGrantPrivileged: boolean;
}) {
  const router = useRouter();
  const { error, pending, run, setError } = useAction();
  const roles = canGrantPrivileged ? ALL : (["member", "viewer"] as Role[]);
  return (
    <div className="flex flex-col items-start gap-1.5 sm:items-end">
      <div className="flex flex-wrap items-center gap-2">
        {editable ? (
          <>
            <label className="sr-only" htmlFor={`role-${userId}`}>
              Role for {name}
            </label>
            <select
              id={`role-${userId}`}
              defaultValue={role}
              disabled={pending}
              onChange={(e) => void run(() => api.changeRole(workspaceId, userId, e.target.value as Role), "The role was not changed.")}
              className="h-8 rounded-md border border-line-strong bg-bg px-2 text-[13px] text-text"
            >
              {roles.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <ConfirmAction
              label="Remove"
              confirmLabel="Remove"
              consequence={`${name} loses access to this workspace.`}
              onConfirm={() => run(() => api.removeMember(workspaceId, userId), "The member was not removed.")}
            />
          </>
        ) : (
          <span className="font-mono text-[13px] text-text-2">{role}</span>
        )}
        {isSelf ? (
          <ConfirmAction
            label="Leave"
            confirmLabel="Leave workspace"
            consequence="You lose access unless someone adds you back."
            onConfirm={async () => {
              setError(null);
              try {
                await api.removeMember(workspaceId, userId);
                document.cookie = "bb_workspace=; path=/; max-age=0; samesite=lax";
                router.replace("/app");
                router.refresh();
              } catch (cause) {
                setError(failureMessage(cause, "You did not leave the workspace."));
              }
            }}
          />
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="text-[12px] text-bad">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function CreateWorkspace() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  return (
    <form
      noValidate
      className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const name = String(new FormData(form).get("name") ?? "").trim();
        if (!name) {
          setError("Name the workspace.");
          return;
        }
        setPending(true);
        setError(null);
        try {
          const created = await api.createWorkspace(name);
          document.cookie = `bb_workspace=${encodeURIComponent(created.id)}; path=/; max-age=31536000; samesite=lax`;
          form.reset();
          router.refresh();
        } catch (cause) {
          setError(failureMessage(cause, "The workspace was not created."));
        } finally {
          setPending(false);
        }
      }}
    >
      <Field id="new-workspace" label="New workspace name" hint="A separate tenancy boundary: nothing is shared between workspaces. You become its owner and it gets a Default project.">
        <Input name="name" maxLength={200} />
      </Field>
      <Button type="submit" tone="secondary" disabled={pending} className="sm:mb-[38px]">
        {pending ? "Creating…" : "Create workspace"}
      </Button>
      {error ? (
        <div className="sm:col-span-2">
          <Notice tone="bad">{error}</Notice>
        </div>
      ) : null}
    </form>
  );
}
