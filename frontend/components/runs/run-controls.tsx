"use client";

/**
 * The run page's interactive pieces.
 *
 * - Following: while a run executes in the background, the server page is
 *   re-read every 3 s (only while the tab is visible) and stops at the end.
 *   Nothing is animated that the server did not report.
 * - Evaluate: appends an evaluation; earlier ones stay readable.
 * - Export, PDF, cancel, delete: plain endpoints, refusals shown as worded.
 * - Bot reply: a run paused on the manual or offline adapter waits for the
 *   bot's reply as text or audio; this sends it to the run's own endpoint.
 */

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Download, FileAudio, Loader2, RefreshCw, Send } from "lucide-react";

import { ConfirmAction, PrintButton, Tabs, failureMessage } from "@/components/ui/interactive";
import { Button, Notice, buttonClass } from "@/components/ui/primitives";
import { api, runExportUrl } from "@/lib/api/client";

const REFRESH_MS = 3000;

export function RunFollower({ active }: { active: boolean }) {
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
    <p role="status" className="no-print flex items-center gap-2 text-[13px] text-busy">
      <span aria-hidden="true" className="bb-pulse size-2 rounded-full bg-busy" />
      Running on the server. This page re-reads the run every {REFRESH_MS / 1000} s until it finishes.
    </p>
  );
}

export function EvaluateButton({ runId, again }: { runId: string; again: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  return (
    <span className="inline-flex flex-col items-end gap-1">
      <Button
        tone={again ? "secondary" : "primary"}
        size="sm"
        disabled={pending}
        onClick={async () => {
          setPending(true);
          setError(null);
          try {
            await api.evaluateRun(runId);
            router.refresh();
          } catch (cause) {
            setError(failureMessage(cause, "The evaluation failed."));
          } finally {
            setPending(false);
          }
        }}
      >
        {pending ? <Loader2 aria-hidden="true" className="size-3.5 animate-spin" /> : <RefreshCw aria-hidden="true" className="size-3.5" />}
        {pending ? "Evaluating…" : again ? "Evaluate again" : "Evaluate this run"}
      </Button>
      {error ? (
        <span role="alert" className="text-[12px] text-bad">
          {error}
        </span>
      ) : null}
    </span>
  );
}

export function RunActions({
  runId,
  finished,
  inFlight,
  canEdit,
  canDelete,
}: {
  runId: string;
  finished: boolean;
  inFlight: boolean;
  canEdit: boolean;
  canDelete: boolean;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="flex flex-col items-start gap-2 md:items-end">
      <div className="flex flex-wrap items-center gap-2">
        <a href={runExportUrl(runId, "json")} download className={buttonClass("secondary", "sm")}>
          <Download aria-hidden="true" className="size-3.5" />
          JSON
        </a>
        <a href={runExportUrl(runId, "csv")} download className={buttonClass("secondary", "sm")}>
          <Download aria-hidden="true" className="size-3.5" />
          CSV
        </a>
        <PrintButton />
        {!finished && canEdit ? (
          <ConfirmAction
            label="Cancel run"
            confirmLabel="Cancel it"
            consequence={inFlight ? "Stops it after the current step." : "Ends it now."}
            onConfirm={async () => {
              setError(null);
              try {
                await api.cancelRun(runId);
                router.refresh();
              } catch (cause) {
                setError(failureMessage(cause, "The run could not be cancelled."));
              }
            }}
          />
        ) : null}
        {finished && canDelete ? (
          <ConfirmAction
            label="Delete…"
            confirmLabel="Delete permanently"
            consequence="Deletes the run, its turns, evaluations and audio."
            onConfirm={async () => {
              setError(null);
              try {
                await api.deleteRun(runId);
                router.replace("/app/runs");
                router.refresh();
              } catch (cause) {
                setError(failureMessage(cause, "The run could not be deleted."));
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

/**
 * The bot's reply for a paused run. `kind` follows what the run is waiting
 * for: text for an offline simulation, audio for the manual voice adapter.
 * An empty text reply is allowed and recorded as silence - a finding about
 * the bot, not an error. A malformed upload is refused and the run keeps
 * waiting, so the operator can try again.
 */
export function BotReply({ runId, turn, kind }: { runId: string; turn: number; kind: "text" | "audio" }) {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmSilence, setConfirmSilence] = useState(false);

  async function send() {
    setPending(true);
    setError(null);
    try {
      if (kind === "text") await api.supplyBotText(runId, text);
      else if (file) await api.supplyBotAudio(runId, file);
      setText("");
      setFile(null);
      setConfirmSilence(false);
      if (fileRef.current) fileRef.current.value = "";
      router.refresh();
    } catch (cause) {
      setError(failureMessage(cause, "The reply was not accepted."));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-3">
      {kind === "text" ? (
        <>
          <label htmlFor="bot-reply" className="block text-[13px] font-medium text-text">
            What the bot said on turn {turn}
          </label>
          <textarea
            id="bot-reply"
            value={text}
            maxLength={2000}
            onChange={(e) => {
              setText(e.target.value);
              setConfirmSilence(false);
            }}
            rows={3}
            className="block w-full rounded-md border border-line-strong bg-bg px-3 py-2 text-[14px] text-text focus-visible:border-accent"
          />
          {confirmSilence ? (
            <Notice tone="warn">Sending nothing records that the bot stayed silent, which counts against the bot. Send again to confirm.</Notice>
          ) : null}
        </>
      ) : (
        <>
          <label htmlFor="bot-audio" className="block text-[13px] font-medium text-text">
            The bot&rsquo;s reply for turn {turn}, as an audio file
          </label>
          <input
            id="bot-audio"
            ref={fileRef}
            type="file"
            accept="audio/*,.wav"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-[13px] text-text-2 file:mr-3 file:h-9 file:rounded-md file:border file:border-line-strong file:bg-bg file:px-3 file:text-[13px] file:font-medium file:text-text hover:file:bg-bg-soft"
          />
          <p className="text-[12px] text-text-3">It is validated and transcribed like any reply. A file that cannot be read is refused and the run keeps waiting.</p>
        </>
      )}
      {error ? <Notice tone="bad">{error}</Notice> : null}
      <Button
        tone="primary"
        size="sm"
        disabled={pending || (kind === "audio" && !file)}
        onClick={() => {
          if (kind === "text" && text.trim() === "" && !confirmSilence) {
            setConfirmSilence(true);
            return;
          }
          void send();
        }}
      >
        {pending ? <Loader2 aria-hidden="true" className="size-3.5 animate-spin" /> : kind === "text" ? <Send aria-hidden="true" className="size-3.5" /> : <FileAudio aria-hidden="true" className="size-3.5" />}
        {pending ? "Sending…" : kind === "text" ? "Send reply" : "Upload reply"}
      </Button>
    </div>
  );
}

/**
 * Tabs for the run page. Every panel is rendered and only hidden on screen,
 * so the print stylesheet can show all of them in the saved PDF.
 */
export function RunTabs({ tabs }: { tabs: { id: string; label: string; badge?: ReactNode; panel: ReactNode }[] }) {
  const [active, setActive] = useState(tabs[0]?.id ?? "");
  return (
    <div className="min-w-0">
      <div className="no-print">
        <Tabs label="Run sections" tabs={tabs.map((t) => ({ id: t.id, label: t.label, badge: t.badge }))} value={active} onChange={setActive} />
      </div>
      {tabs.map((t) => (
        <div key={t.id} role="tabpanel" aria-label={t.label} data-tabpanel className={t.id === active ? "pt-5" : "hidden pt-5 print:block"}>
          <h2 className="print-only mb-3 text-[18px] font-semibold">{t.label}</h2>
          {t.panel}
        </div>
      ))}
    </div>
  );
}
