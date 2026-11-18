"use client";

/**
 * Export and delete for one run. Exports are plain links to the real
 * endpoints, relative so the first-party session cookie travels with them.
 * Delete asks twice in the page itself - a browser confirm() blocks the
 * tab - and is offered only for a finished run to a caller the page found
 * to be admin or owner of its workspace. The server checks both again, and
 * any refusal is shown as worded.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, buttonClass } from "@/components/ui/primitives";
import { ApiError, api, runExportUrl } from "@/lib/api/client";

export function RunActions({
  runId,
  finished,
  canDelete,
}: {
  runId: string;
  finished: boolean;
  canDelete: boolean;
}) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setPending(true);
    setError(null);
    try {
      await api.deleteRun(runId);
      router.replace("/app/runs");
      router.refresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The run could not be deleted.");
      setPending(false);
      setConfirming(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <a href={runExportUrl(runId, "json")} download className={buttonClass("default", "sm")}>
        Export JSON
      </a>
      <a href={runExportUrl(runId, "csv")} download className={buttonClass("default", "sm")}>
        Export CSV
      </a>
      {finished && canDelete ? (
        confirming ? (
          <>
            <span className="text-[12px] text-text-muted">
              Deletes the run, its turns, evaluations and audio. Not reversible.
            </span>
            <Button size="sm" tone="danger" disabled={pending} onClick={() => void remove()}>
              {pending ? "Deleting…" : "Delete permanently"}
            </Button>
            <Button size="sm" disabled={pending} onClick={() => setConfirming(false)}>
              Keep it
            </Button>
          </>
        ) : (
          <Button size="sm" onClick={() => setConfirming(true)}>
            Delete…
          </Button>
        )
      ) : null}
      {error ? (
        <p role="alert" className="basis-full text-[12px] text-bad">
          {error}
        </p>
      ) : null}
    </div>
  );
}
