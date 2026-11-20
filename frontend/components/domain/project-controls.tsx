"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Plus } from "lucide-react";

import { Field, Input, Select, Textarea } from "@/components/ui/field";
import { ConfirmAction, Dialog, failureMessage } from "@/components/ui/interactive";
import { Button, Notice } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";

/**
 * Create a project in a workspace the caller administers. Opens itself when
 * the page is visited with `?create=1` (the command menu and quick actions
 * link there).
 */
export function CreateProjectButton({ workspaces }: { workspaces: { id: string; name: string }[] }) {
  const router = useRouter();
  const params = useSearchParams();
  const [open, setOpen] = useState(params.get("create") === "1" && workspaces.length > 0);
  const [error, setError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (workspaces.length === 0) return null;

  function close() {
    setOpen(false);
    setError(null);
    setNameError(null);
    if (params.get("create")) router.replace("/app/projects");
  }

  return (
    <>
      <Button tone="primary" onClick={() => setOpen(true)}>
        <Plus aria-hidden="true" className="size-4" />
        New project
      </Button>
      <Dialog open={open} onClose={close} title="New project" description="Projects hold test suites. Only admins and owners create them.">
        <form
          id="create-project"
          noValidate
          className="space-y-4"
          onSubmit={async (event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            const name = String(data.get("name") ?? "").trim();
            const description = String(data.get("description") ?? "").trim();
            if (!name) {
              setNameError("Give the project a name.");
              return;
            }
            setNameError(null);
            setPending(true);
            setError(null);
            try {
              const project = await api.createProjectWith(String(data.get("workspace")), {
                name,
                description: description || null,
              });
              router.push(`/app/projects/${project.id}`);
              router.refresh();
            } catch (cause) {
              setError(failureMessage(cause, "The project was not created."));
              setPending(false);
            }
          }}
        >
          {workspaces.length > 1 ? (
            <Field id="project-workspace" label="Workspace">
              <Select name="workspace" defaultValue={workspaces[0].id}>
                {workspaces.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </Select>
            </Field>
          ) : (
            <input type="hidden" name="workspace" value={workspaces[0].id} />
          )}
          <Field id="project-name" label="Name" error={nameError}>
            <Input name="name" maxLength={200} autoFocus placeholder="Insurance helpline bot" />
          </Field>
          <Field id="project-description" label="Description" optional>
            <Textarea name="description" maxLength={2000} rows={3} />
          </Field>
          {error ? <Notice tone="bad">{error}</Notice> : null}
          <div className="flex justify-end gap-2 pt-1">
            <Button tone="ghost" onClick={close}>
              Cancel
            </Button>
            <Button type="submit" tone="primary" disabled={pending}>
              {pending ? "Creating…" : "Create project"}
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}

/** Rename, describe and delete one project. Admin and owner only. */
export function ProjectSettings({
  id,
  name,
  description,
}: {
  id: string;
  name: string;
  description: string | null;
}) {
  const router = useRouter();
  const [draftName, setDraftName] = useState(name);
  const [draftDescription, setDraftDescription] = useState(description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, setPending] = useState(false);
  const changed = draftName.trim() !== name || draftDescription.trim() !== (description ?? "");

  return (
    <div className="space-y-6">
      <form
        className="space-y-4"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!draftName.trim()) {
            setError("A project needs a name.");
            return;
          }
          setPending(true);
          setError(null);
          setSaved(false);
          try {
            await api.updateProject(id, { name: draftName.trim(), description: draftDescription.trim() || null });
            setSaved(true);
            router.refresh();
          } catch (cause) {
            setError(failureMessage(cause, "The project was not saved."));
          } finally {
            setPending(false);
          }
        }}
      >
        <Field id="edit-project-name" label="Name">
          <Input value={draftName} onChange={(e) => setDraftName(e.target.value)} maxLength={200} />
        </Field>
        <Field id="edit-project-description" label="Description" optional>
          <Textarea value={draftDescription} onChange={(e) => setDraftDescription(e.target.value)} maxLength={2000} rows={3} />
        </Field>
        {error ? <Notice tone="bad">{error}</Notice> : null}
        {saved && !changed ? <Notice tone="ok">Saved.</Notice> : null}
        <Button type="submit" tone="primary" size="sm" disabled={pending || !changed}>
          {pending ? "Saving…" : "Save changes"}
        </Button>
      </form>
      <DeleteProject id={id} />
    </div>
  );
}

function DeleteProject({ id }: { id: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="space-y-2 border-t border-line pt-5">
      <p className="text-[14px] font-medium text-text">Delete project</p>
      <p className="text-[13px] leading-relaxed text-text-3">
        Only an empty project can be deleted. While it holds suites the server refuses, so no suite, scenario or run is
        ever lost with it.
      </p>
      <ConfirmAction
        label="Delete project…"
        confirmLabel="Delete permanently"
        consequence="Not reversible."
        onConfirm={async () => {
          setError(null);
          try {
            await api.deleteProject(id);
            router.replace("/app/projects");
            router.refresh();
          } catch (cause) {
            setError(failureMessage(cause, "The project was not deleted."));
          }
        }}
      />
      {error ? <Notice tone="bad">{error}</Notice> : null}
    </div>
  );
}
