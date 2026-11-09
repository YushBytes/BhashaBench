/**
 * The components that stop the interface overclaiming.
 *
 * These are not decoration and not optional. The API carries fields that
 * exist specifically so a client cannot misrepresent a run -
 * `bot_audio_externally_received`, `uses_language_model`,
 * `measurement_note`, `evon_status`, `telephony_status` - and these are the
 * components that render them. Structural rather than copy, so a new page
 * cannot forget to be honest.
 */

import type { ReactNode } from "react";

import { cx } from "@/components/ui/primitives";
import type { ExecutionMode, Run } from "@/lib/api/types";

type Level = "note" | "caution";

/**
 * A qualification on what the reader is looking at.
 *
 * Quiet by default: these appear on every run, and an alarm-coloured banner
 * repeated on every page stops being read. `caution` is for the case where
 * the label and the evidence actually disagree.
 */
export function Caveat({
  level = "note",
  title,
  children,
}: {
  level?: Level;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div
      className={cx(
        "flex gap-2.5 rounded-md border px-3 py-2.5",
        level === "caution"
          ? "border-warn/30 bg-warn-dim"
          : "border-line bg-surface-inset",
      )}
    >
      <span
        aria-hidden="true"
        className={cx(
          "mt-1.5 inline-block size-1.5 shrink-0 rounded-full",
          level === "caution" ? "bg-warn" : "bg-text-muted",
        )}
      />
      <div className="min-w-0">
        <p
          className={cx(
            "text-[13px] font-medium",
            level === "caution" ? "text-warn" : "text-text",
          )}
        >
          {title}
        </p>
        {children ? (
          <p className="mt-0.5 text-[13px] leading-relaxed text-text-dim">{children}</p>
        ) : null}
      </div>
    </div>
  );
}

/**
 * What a run does and does not establish, derived from the run itself.
 *
 * Every line here is computed from a field, never from the mode label
 * alone. That is the point: a run created as `external_bot_test` whose
 * replies were fixtures reports `bot_audio_externally_received: false`, and
 * this component says so rather than repeating the label it was given.
 */
export function RunEvidence({ run }: { run: Run }) {
  const caveats: Array<{ level: Level; title: string; body: string }> = [];

  if (run.mode === "external_bot_test" && !run.bot_audio_externally_received) {
    caveats.push({
      level: "caution",
      title: "Labelled an external bot test, but no external audio arrived",
      body:
        "Every bot reply in this run came from inside the process. The run " +
        "does not establish anything about an external bot, whatever it was " +
        "created as.",
    });
  } else if (run.mode !== "external_bot_test") {
    caveats.push({
      level: "note",
      title: "No external bot was contacted",
      body:
        MODE_EVIDENCE[run.mode] ??
        "Bot audio did not come from outside this process.",
    });
  }

  if (!run.uses_language_model) {
    caveats.push({
      level: "note",
      title: "The caller is a rule engine, not a language model",
      body:
        "Utterances come from reviewed per-language phrase tables and a " +
        "state machine. Gnani Evon is not integrated. An utterance no rule " +
        "anticipates produces a clarification request — that is the ceiling " +
        "of a rule engine, and it bounds what this run can show.",
    });
  }

  caveats.push({
    level: "note",
    title: "Measurements, not scores",
    body:
      "Counts and durations on this page were measured. There is no accuracy " +
      "figure, word error rate or quality verdict: none is computable without " +
      "a reviewed reference transcript, and evaluation is a later phase.",
  });

  return (
    <div className="space-y-2">
      {caveats.map((caveat) => (
        <Caveat key={caveat.title} level={caveat.level} title={caveat.title}>
          {caveat.body}
        </Caveat>
      ))}
    </div>
  );
}

const MODE_EVIDENCE: Partial<Record<ExecutionMode, string>> = {
  offline_simulation:
    "This run moved no audio at all. It exercised the caller's decisions and nothing else.",
  audio_fixture_test:
    "Every stage ran, with the bot stubbed by fixture audio. It establishes that the pipeline works end to end, not that any bot does.",
};

/**
 * The API's own sentence about what its counts mean.
 *
 * Rendered verbatim from `measurement_note` rather than paraphrased: the
 * backend wrote that wording deliberately, and a UI paraphrase is how a
 * careful qualification turns into a vague one.
 */
export function MeasurementNote({ note }: { note: string }) {
  if (!note) return null;
  return (
    <p className="text-[12px] leading-relaxed text-text-muted">{note}</p>
  );
}
