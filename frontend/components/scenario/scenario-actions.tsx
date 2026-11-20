"use client";

/**
 * Duplicate, archive or restore, and delete one scenario.
 *
 * A scenario that recorded runs use cannot be deleted - their reports must
 * stay readable - and the server's 409 says to archive it instead; that
 * refusal is shown as worded and the page stays put. Destructive steps are
 * confirmed in the page.
 */

import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { Archive, ArchiveRestore, Copy } from "lucide-react";

import { failureMessage } from "@/components/ui/interactive";
import { Button, Notice } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";

export function ScenarioActions({
  scenarioId,
  suiteId,
  name,
  archived,
  canEdit,
  canDelete,
}: {
  scenarioId: string;
  suiteId: string;
  name: string;
  archived: boolean;
  canEdit: boolean;
  canDelete: boolean;
}) {
  const router = useRouter();
  const copyId = useId();
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
      setError(failureMessage(cause, fallback));
    } finally {
      setBusy(false);
    }
  }

  if (!canEdit) {
    return <p className="text-[13px] text-text-3">Your role in this workspace is viewer, so this scenario is read-only to you.</p>;
  }

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <label htmlFor={copyId} className="block text-[14px] font-medium text-text">
          Duplicate in this suite
        </label>
        <p className="text-[12px] text-text-3">A new scenario with its own id and no runs.</p>
        <div className="flex flex-wrap gap-2">
          <input
            id={copyId}
            value={copyName}
            onChange={(event) => setCopyName(event.target.value)}
            maxLength={200}
            className="h-8 min-w-0 flex-1 rounded-md border border-line-strong bg-bg px-2.5 font-mono text-[13px] text-text"
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
            <Copy aria-hidden="true" className="size-3.5" />
            Duplicate
          </Button>
        </div>
      </section>

      <section className="space-y-2 border-t border-line pt-5">
        <h3 className="text-[14px] font-medium text-text">{archived ? "Archived" : "Archive"}</h3>
        <p className="text-[12px] leading-relaxed text-text-3">
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
          {archived ? <ArchiveRestore aria-hidden="true" className="size-3.5" /> : <Archive aria-hidden="true" className="size-3.5" />}
          {archived ? "Restore" : "Archive"}
        </Button>
      </section>

      {canDelete ? (
        <section className="space-y-2 border-t border-line pt-5">
          <h3 className="text-[14px] font-medium text-text">Delete</h3>
          <p className="text-[12px] leading-relaxed text-text-3">
            Only for a scenario no run has used. One with recorded runs is refused, so their reports stay readable; archive it instead.
          </p>
          {confirmDelete ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[12px] text-text-3">Not reversible.</span>
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
              <Button size="sm" tone="ghost" disabled={busy} onClick={() => setConfirmDelete(false)}>
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
      {done ? <Notice tone="ok">{done}</Notice> : null}
    </div>
  );
}
