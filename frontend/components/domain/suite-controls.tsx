"use client";

/**
 * Suite authoring: create, rename, delete, move scenarios between suites,
 * and import or export a scenario bundle. Every action is the real endpoint
 * and every refusal is shown as the server worded it.
 *
 * Delete asks once; a suite still holding scenarios is refused by the server
 * (409), and only then does the control offer to delete them with it, saying
 * so. A scenario that recorded runs use blocks even that, so history is never
 * lost to a suite deletion.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { useId, useState } from "react";
import { Download, Plus, Upload } from "lucide-react";

import { Field, Input, Select, Textarea } from "@/components/ui/field";
import { Dialog, failureMessage } from "@/components/ui/interactive";
import { Button, Notice } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import type { BundleImportResult } from "@/lib/api/types";

export function CreateSuiteButton({ projects }: { projects: { id: string; label: string }[] }) {
  const router = useRouter();
  const params = useSearchParams();
  const preferred = params.get("project");
  const [open, setOpen] = useState(params.get("create") === "1" && projects.length > 0);
  const [error, setError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  if (projects.length === 0) return null;

  function close() {
    setOpen(false);
    setError(null);
    if (params.get("create")) router.replace("/app/suites");
  }

  return (
    <>
      <Button tone="primary" onClick={() => setOpen(true)}>
        <Plus aria-hidden="true" className="size-4" />
        New suite
      </Button>
      <Dialog open={open} onClose={close} title="New test suite" description="A suite groups scenarios you run together. Names are unique within a project.">
        <form
          noValidate
          className="space-y-4"
          onSubmit={async (event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            const name = String(data.get("name") ?? "").trim();
            if (!name) {
              setNameError("Give the suite a name.");
              return;
            }
            setNameError(null);
            setPending(true);
            setError(null);
            try {
              const suite = await api.createSuiteFull({
                name,
                project_id: String(data.get("project")),
                description: String(data.get("description") ?? "").trim() || null,
              });
              router.push(`/app/suites/${suite.id}`);
              router.refresh();
            } catch (cause) {
              setError(failureMessage(cause, "The suite was not created."));
              setPending(false);
            }
          }}
        >
          <Field id="suite-project" label="Project">
            <Select name="project" defaultValue={projects.some((p) => p.id === preferred) ? (preferred ?? undefined) : projects[0].id}>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field id="suite-name" label="Name" error={nameError}>
            <Input name="name" maxLength={200} autoFocus placeholder="Release check" />
          </Field>
          <Field id="suite-description" label="Description" optional>
            <Textarea name="description" maxLength={2000} rows={3} />
          </Field>
          {error ? <Notice tone="bad">{error}</Notice> : null}
          <div className="flex justify-end gap-2 pt-1">
            <Button tone="ghost" onClick={close}>
              Cancel
            </Button>
            <Button type="submit" tone="primary" disabled={pending}>
              {pending ? "Creating…" : "Create suite"}
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}

/** Rename and delete one suite. Shown only with edit rights. */
export function SuiteActions({
  id,
  name,
  canEdit,
  afterDelete,
}: {
  id: string;
  name: string;
  canEdit: boolean;
  /** Where to go once the suite is gone; omitted means stay and refresh. */
  afterDelete?: string;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<"idle" | "rename" | "delete" | "cascade">("idle");
  const [draft, setDraft] = useState(name);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!canEdit) return null;

  async function run(action: () => Promise<unknown>, deleting = false) {
    setPending(true);
    setError(null);
    try {
      await action();
      setMode("idle");
      if (deleting && afterDelete) router.replace(afterDelete);
      router.refresh();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409 && mode === "delete") {
        setMode("cascade");
        setError(cause.message);
      } else {
        setError(failureMessage(cause, "The suite was not changed."));
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {mode === "rename" ? (
          <>
            <input
              aria-label={`New name for ${name}`}
              value={draft}
              maxLength={200}
              onChange={(e) => setDraft(e.target.value)}
              className="h-8 min-w-0 flex-1 rounded-md border border-line-strong bg-bg px-2.5 text-[13px] text-text"
            />
            <Button size="sm" tone="primary" disabled={pending || !draft.trim()} onClick={() => run(() => api.renameSuite(id, draft.trim()))}>
              Save
            </Button>
            <Button size="sm" tone="ghost" disabled={pending} onClick={() => setMode("idle")}>
              Cancel
            </Button>
          </>
        ) : mode === "idle" ? (
          <>
            <Button size="sm" onClick={() => { setDraft(name); setMode("rename"); }}>
              Rename
            </Button>
            <Button size="sm" onClick={() => setMode("delete")}>
              Delete…
            </Button>
          </>
        ) : null}
      </div>
      {mode === "delete" ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12px] text-text-3">Delete this suite?</span>
          <Button size="sm" tone="danger" disabled={pending} onClick={() => run(() => api.deleteSuite(id, false), true)}>
            Delete
          </Button>
          <Button size="sm" tone="ghost" disabled={pending} onClick={() => setMode("idle")}>
            Keep it
          </Button>
        </div>
      ) : null}
      {mode === "cascade" ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12px] text-text-3">Delete it and every scenario in it? Not reversible.</span>
          <Button size="sm" tone="danger" disabled={pending} onClick={() => run(() => api.deleteSuite(id, true), true)}>
            Delete all
          </Button>
          <Button size="sm" tone="ghost" disabled={pending} onClick={() => { setMode("idle"); setError(null); }}>
            Keep it
          </Button>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-[12px] text-bad">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** Move one scenario into another suite, renaming if the target has the name. */
export function MoveScenario({
  scenarioId,
  scenarioName,
  targets,
}: {
  scenarioId: string;
  scenarioName: string;
  targets: { id: string; label: string }[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  if (targets.length === 0) return null;
  return (
    <>
      <Button size="sm" tone="ghost" onClick={() => setOpen(true)}>
        Move…
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={`Move ${scenarioName}`}
        description="Its recorded runs stay attached to the scenario and keep their reports."
      >
        <form
          className="space-y-4"
          onSubmit={async (event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            setPending(true);
            setError(null);
            try {
              await api.moveScenario(scenarioId, String(data.get("target")), String(data.get("rename") ?? "").trim() || null);
              setOpen(false);
              router.refresh();
            } catch (cause) {
              setError(failureMessage(cause, "The scenario was not moved."));
            } finally {
              setPending(false);
            }
          }}
        >
          <Field id={`move-${scenarioId}`} label="Into suite">
            <Select name="target">
              {targets.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field id={`move-name-${scenarioId}`} label="New name" optional hint="Only if the target suite already uses this name. Lowercase letters, digits, - and _.">
            <Input name="rename" maxLength={200} pattern="[a-z0-9][a-z0-9_\-]*" />
          </Field>
          {error ? <Notice tone="bad">{error}</Notice> : null}
          <div className="flex justify-end gap-2">
            <Button tone="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" tone="primary" disabled={pending}>
              {pending ? "Moving…" : "Move scenario"}
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}

/** Download the suite as a scenario bundle (YAML), from the export endpoint. */
export function ExportBundleButton({ suiteId, suiteName }: { suiteId: string; suiteName: string }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Button
        size="sm"
        disabled={pending}
        onClick={async () => {
          setPending(true);
          setError(null);
          try {
            const bundle = await api.exportSuite(suiteId);
            const url = URL.createObjectURL(new Blob([bundle.yaml], { type: "application/yaml" }));
            const link = document.createElement("a");
            link.href = url;
            link.download = `${suiteName.replace(/[^a-z0-9_-]+/gi, "_").toLowerCase() || "suite"}.yaml`;
            link.click();
            URL.revokeObjectURL(url);
          } catch (cause) {
            setError(failureMessage(cause, "The bundle could not be exported."));
          } finally {
            setPending(false);
          }
        }}
      >
        <Download aria-hidden="true" className="size-3.5" />
        {pending ? "Exporting…" : "Export bundle"}
      </Button>
      {error ? (
        <span role="alert" className="text-[12px] text-bad">
          {error}
        </span>
      ) : null}
    </span>
  );
}

/**
 * Import a bundle: a dry run first, which validates every entry and imports
 * nothing, then the real import. `atomic` imports all or none.
 */
export function ImportBundleButton({ suiteId }: { suiteId: string }) {
  const router = useRouter();
  const fieldId = useId();
  const [open, setOpen] = useState(false);
  const [yaml, setYaml] = useState("");
  const [atomic, setAtomic] = useState(true);
  const [result, setResult] = useState<BundleImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function send(dryRun: boolean) {
    setPending(true);
    setError(null);
    try {
      const outcome = await api.importBundle(suiteId, { yaml, dry_run: dryRun, atomic });
      setResult(outcome);
      if (!dryRun && outcome.committed) router.refresh();
    } catch (cause) {
      setError(failureMessage(cause, "The bundle was not imported."));
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        <Upload aria-hidden="true" className="size-3.5" />
        Import bundle
      </Button>
      <Dialog
        open={open}
        size="lg"
        onClose={() => {
          setOpen(false);
          setResult(null);
          setError(null);
        }}
        title="Import a scenario bundle"
        description="Paste a bundle exported from BhashaBench or written to docs/SCENARIO_FORMAT.md. Check it first; nothing is stored until you import."
        footer={
          <>
            <Button tone="secondary" disabled={pending || !yaml.trim()} onClick={() => send(true)}>
              Check bundle
            </Button>
            <Button tone="primary" disabled={pending || !result?.dry_run || result.valid === 0} onClick={() => send(false)}>
              Import {result?.dry_run ? `${result.valid} scenario${result.valid === 1 ? "" : "s"}` : ""}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label htmlFor={fieldId} className="text-[13px] font-medium text-text">
              Bundle YAML
            </label>
            <textarea
              id={fieldId}
              value={yaml}
              onChange={(e) => {
                setYaml(e.target.value);
                setResult(null);
              }}
              rows={12}
              spellCheck={false}
              className="mt-1.5 block w-full rounded-md border border-line-strong bg-bg-soft p-3 font-mono text-[12px] text-text"
            />
          </div>
          <label className="flex items-center gap-2 text-[13px] text-text-2">
            <input type="checkbox" checked={atomic} onChange={(e) => { setAtomic(e.target.checked); setResult(null); }} className="size-4" />
            All or nothing: if any entry is invalid, import none
          </label>
          {error ? <Notice tone="bad">{error}</Notice> : null}
          {result ? (
            <div className="rounded-md border border-line p-3 text-[13px]" role="status">
              <p className="font-medium text-text">
                {result.dry_run
                  ? `Checked: ${result.valid} of ${result.total} valid, ${result.failed} invalid. Nothing stored yet.`
                  : result.committed
                    ? `Imported ${result.imported} of ${result.total}.`
                    : `Nothing imported: ${result.failed} invalid entr${result.failed === 1 ? "y" : "ies"}.`}
              </p>
              {result.duplicates.length > 0 ? (
                <p className="mt-1 text-text-3">Already in this suite: {result.duplicates.join(", ")}</p>
              ) : null}
              {result.entry_errors.length > 0 ? (
                <ul className="mt-2 space-y-1 text-[12px] text-bad">
                  {result.entry_errors.map((entry) => (
                    <li key={entry.index}>
                      Entry {entry.index + 1}
                      {entry.name ? ` (${entry.name})` : ""}:{" "}
                      {entry.errors.map((e) => `${e.field ? `${e.field}: ` : ""}${e.message}`).join("; ")}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
      </Dialog>
    </>
  );
}
