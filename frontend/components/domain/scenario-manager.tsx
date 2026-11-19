"use client";

/**
 * Edit, duplicate, archive or delete one scenario.
 *
 * Every action is the real endpoint, and every refusal is shown as the
 * server worded it. That matters most for Delete: a scenario that recorded
 * runs use cannot be deleted - their reports must stay readable - and the
 * server's 409 says to archive it instead, so the page offers that next.
 * Destructive steps are confirmed in the page; a browser confirm() would
 * block the tab.
 *
 * The editor holds the stored specification as JSON, which is valid YAML,
 * so it validates and saves through the same routes as an upload. The
 * original file's comments are not kept by the server and so cannot be
 * shown here.
 */

import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import { Button } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import type { ScenarioValidation } from "@/lib/api/types";

function message(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

export function ScenarioManager({
  scenarioId,
  suiteId,
  name,
  spec,
  archived,
  canEdit,
  canDelete,
}: {
  scenarioId: string;
  suiteId: string;
  name: string;
  spec: unknown;
  archived: boolean;
  canEdit: boolean;
  canDelete: boolean;
}) {
  const router = useRouter();
  const editorId = useId();
  const copyId = useId();
  const [text, setText] = useState(() => JSON.stringify(spec, null, 2));
  const [validation, setValidation] = useState<ScenarioValidation | null>(null);
  const [copyName, setCopyName] = useState(`${name}_copy`.slice(0, 200));
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function act(action: () => Promise<string | null>, fallback: string) {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const result = await action();
      if (result) setDone(result);
    } catch (cause) {
      setError(message(cause, fallback));
    } finally {
      setBusy(false);
    }
  }

  if (!canEdit) {
    return (
      <p className="text-[13px] text-text-muted">
        Your role in this workspace is viewer, so this scenario is read-only to you.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <label htmlFor={editorId} className="block text-[13px] font-medium text-text">
          Specification
        </label>
        <p className="text-[12px] leading-relaxed text-text-muted">
          Shown as JSON, which is valid YAML. Validate, then save: the server checks it
          again. Renaming keeps the same scenario id, so its runs still point to it.
        </p>
        <textarea
          id={editorId}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setValidation(null);
          }}
          rows={16}
          spellCheck={false}
          className="block w-full rounded-md border border-line-strong bg-surface-raised px-3 py-2 font-mono text-[12px] text-text"
        />
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={busy || !text.trim()}
            onClick={() =>
              act(async () => {
                setValidation(await api.validateScenario(text));
                return null;
              }, "Validation failed.")
            }
          >
            Validate
          </Button>
          <Button
            size="sm"
            tone="primary"
            disabled={busy || !validation?.valid}
            onClick={() =>
              act(async () => {
                const saved = await api.updateScenario(scenarioId, text);
                router.refresh();
                return `Saved "${saved.name}".`;
              }, "The scenario was not saved.")
            }
          >
            Save changes
          </Button>
        </div>
        {validation !== null ? (
          validation.valid ? (
            <p role="status" className="text-[12px] text-ok">Valid. It can be saved.</p>
          ) : (
            <ul role="alert" className="space-y-1 text-[12px] text-bad">
              {validation.errors.map((e, i) => (
                <li key={`${e.field}-${i}`}>
                  <span className="font-mono">{e.field}</span>: {e.message}
                </li>
              ))}
            </ul>
          )
        ) : null}
      </section>

      <section className="space-y-2 border-t border-line pt-4">
        <label htmlFor={copyId} className="block text-[13px] font-medium text-text">
          Duplicate in this suite
        </label>
        <div className="flex flex-wrap gap-2">
          <input
            id={copyId}
            value={copyName}
            onChange={(event) => setCopyName(event.target.value)}
            maxLength={200}
            className="h-9 min-w-[14rem] flex-1 rounded-md border border-line-strong bg-surface-raised px-2.5 font-mono text-[13px] text-text"
          />
          <Button
            size="sm"
            disabled={busy || !copyName.trim()}
            onClick={() =>
              act(async () => {
                const copy = await api.copyScenario(scenarioId, suiteId, copyName.trim());
                router.push(`/app/scenarios/${copy.id}`);
                return `Created "${copy.name}".`;
              }, "The scenario was not duplicated.")
            }
          >
            Duplicate
          </Button>
        </div>
      </section>

      <section className="space-y-2 border-t border-line pt-4">
        <h3 className="text-[13px] font-medium text-text">{archived ? "Archived" : "Archive"}</h3>
        <p className="text-[12px] leading-relaxed text-text-muted">
          {archived
            ? "Hidden from listings and refused for new runs. Its recorded runs and reports are unaffected."
            : "Hides it from listings and refuses new runs of it, while every recorded run and report stays readable. Reversible."}
        </p>
        <Button
          size="sm"
          disabled={busy}
          onClick={() =>
            act(async () => {
              if (archived) await api.restoreScenario(scenarioId);
              else await api.archiveScenario(scenarioId);
              router.refresh();
              return archived ? "Restored." : "Archived.";
            }, "The change was not applied.")
          }
        >
          {archived ? "Restore" : "Archive"}
        </Button>
      </section>

      {canDelete ? (
        <section className="space-y-2 border-t border-line pt-4">
          <h3 className="text-[13px] font-medium text-text">Delete</h3>
          <p className="text-[12px] leading-relaxed text-text-muted">
            Only for a scenario no run has used. One with recorded runs is refused, so their
            reports stay readable; archive it instead.
          </p>
          {confirmDelete ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[12px] text-text-muted">Not reversible.</span>
              <Button
                size="sm"
                tone="danger"
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    await api.deleteScenario(scenarioId);
                    router.replace("/app/scenarios");
                    router.refresh();
                    return null;
                  }, "The scenario was not deleted.").finally(() => setConfirmDelete(false))
                }
              >
                Delete permanently
              </Button>
              <Button size="sm" disabled={busy} onClick={() => setConfirmDelete(false)}>
                Keep it
              </Button>
            </div>
          ) : (
            <Button size="sm" onClick={() => setConfirmDelete(true)}>
              Delete…
            </Button>
          )}
        </section>
      ) : null}

      {error ? (
        <p role="alert" className="text-[12px] text-bad">
          {error}
        </p>
      ) : null}
      {done ? (
        <p role="status" className="text-[12px] text-ok">
          {done}
        </p>
      ) : null}
    </div>
  );
}
