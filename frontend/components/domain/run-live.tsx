"use client";

/**
 * Small client pieces of the run page: auto-refresh while a run is in
 * flight, and the button that evaluates a finished run.
 *
 * Auto-refresh re-renders the server page (which reads the API again) every
 * few seconds while the run is not terminal and the tab is visible, and
 * stops as soon as the run ends - a run executing in the background
 * (`start?background=true`) is followed without the operator reloading.
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";

const REFRESH_MS = 3000;

export function RunAutoRefresh({ active }: { active: boolean }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [active, router]);
  if (!active) return null;
  return (
    <p role="status" className="text-[12px] text-text-dim">
      Following this run - the page refreshes every {REFRESH_MS / 1000} s until it finishes.
    </p>
  );
}

export function EvaluateButton({ runId, again }: { runId: string; again: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  return (
    <div>
      <Button
        tone={again ? "default" : "primary"}
        size="sm"
        disabled={pending}
        onClick={async () => {
          setPending(true);
          setError(null);
          try {
            await api.evaluateRun(runId);
            router.refresh();
          } catch (cause) {
            setError(cause instanceof ApiError ? cause.message : "The evaluation failed.");
          } finally {
            setPending(false);
          }
        }}
      >
        {pending ? "Evaluating…" : again ? "Evaluate again" : "Evaluate this run"}
      </Button>
      {error ? (
        <p role="alert" className="mt-2 text-[12px] text-bad">
          {error}
        </p>
      ) : null}
    </div>
  );
}
