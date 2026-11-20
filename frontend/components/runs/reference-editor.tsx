"use client";

/**
 * A bot turn's reference transcript: reviewed ground truth, the only input
 * WER and CER can be computed from. Without one the evaluator reports them
 * as not reported, never as zero.
 *
 * The draft starts from the newest reference, or else from the system's own
 * transcript, which the reviewer corrects. It is saved only when the reviewer
 * presses Save - a reference copied unedited from the transcript it scores
 * would score 0% by construction. References are append-only on the server.
 */

import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";
import { PenLine } from "lucide-react";

import { failureMessage } from "@/components/ui/interactive";
import { Button } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import type { ReferenceRead } from "@/lib/api/types";
import { formatTimestampShort } from "@/lib/format";

export function ReferenceEditor({
  runId,
  turnIndex,
  transcript,
  canEdit,
}: {
  runId: string;
  turnIndex: number;
  transcript: string | null;
  canEdit: boolean;
}) {
  const router = useRouter();
  const fieldId = useId();
  const [history, setHistory] = useState<ReferenceRead[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .turnReferences(runId, turnIndex)
      .then((result) => live && setHistory(result.references))
      .catch((cause: unknown) => live && setLoadError(failureMessage(cause, "Could not load the reference.")));
    return () => {
      live = false;
    };
  }, [runId, turnIndex]);

  const current = history && history.length > 0 ? history[history.length - 1] : null;

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      const created = await api.addTurnReference(runId, turnIndex, { text: draft });
      setHistory((previous) => [...(previous ?? []), created]);
      setEditing(false);
      setSaved(true);
      router.refresh();
    } catch (cause) {
      setSaveError(failureMessage(cause, "The reference was not saved."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 rounded-md border border-dashed border-line-strong px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-text-3">
          <PenLine aria-hidden="true" className="size-3.5" />
          Reference transcript
        </span>
        {canEdit && !editing && history !== null ? (
          <Button
            size="sm"
            tone="ghost"
            onClick={() => {
              setDraft(current?.text ?? transcript ?? "");
              setSaveError(null);
              setSaved(false);
              setEditing(true);
            }}
          >
            {current ? "Correct" : "Add reference"}
          </Button>
        ) : null}
      </div>

      {loadError ? (
        <p role="alert" className="mt-1 text-[12px] text-bad">
          {loadError}
        </p>
      ) : history === null ? (
        <p className="mt-1 text-[12px] text-text-3">Loading…</p>
      ) : current && !editing ? (
        <div className="mt-1">
          <p className="text-[13px] leading-relaxed text-text">{current.text}</p>
          <p className="mt-0.5 text-[11px] text-text-3">
            {history.length > 1 ? `Revision ${history.length} · ` : ""}
            {current.reviewer ? `${current.reviewer} · ` : ""}
            {formatTimestampShort(current.created_at) ?? current.created_at}
          </p>
        </div>
      ) : !editing ? (
        <p className="mt-1 text-[12px] leading-relaxed text-text-3">
          None recorded, so this turn has no WER or CER.
          {canEdit ? " Add what the bot actually said, as a reviewer heard it." : ""}
        </p>
      ) : null}

      {editing ? (
        <div className="mt-2 space-y-2">
          <label htmlFor={fieldId} className="block text-[12px] text-text-2">
            What the bot actually said. Correct the transcript; do not just accept it.
          </label>
          <textarea
            id={fieldId}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={3}
            className="w-full rounded-md border border-line-strong bg-bg px-2.5 py-2 text-[13px] text-text focus-visible:border-accent"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" tone="primary" disabled={saving || draft.trim() === ""} onClick={() => void save()}>
              {saving ? "Saving…" : "Save reference"}
            </Button>
            <Button size="sm" tone="ghost" disabled={saving} onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
          {saveError ? (
            <p role="alert" className="text-[12px] text-bad">
              {saveError}
            </p>
          ) : null}
        </div>
      ) : null}

      {saved ? (
        <p role="status" className="mt-1 text-[12px] font-medium text-ok">
          Saved. Evaluate again to include it in WER and CER.
        </p>
      ) : null}
    </div>
  );
}
