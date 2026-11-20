/**
 * The status vocabulary.
 *
 * A run status, an outcome, an execution mode, a verdict and a provider's
 * availability are different statements, so they are different components
 * and a reader who learns one badge does not have to re-learn it on the next
 * screen. The words are the ones the product has used since Phase 8.
 *
 * **No status is colour alone.** Every badge pairs its hue with a word, and
 * most with a glyph, so a table reads correctly in greyscale.
 *
 * Blue is not a status. External-bot modes are drawn in solid ink: they are
 * the modes whose results describe a real bot, which deserves weight, not
 * the colour reserved for actions and focus.
 */

import type { ReactNode } from "react";
import {
  Ban,
  CheckCircle2,
  CircleDashed,
  CircleDot,
  Clock,
  Loader2,
  MinusCircle,
  XCircle,
} from "lucide-react";

import { cx } from "./primitives";
import type { ExecutionMode, HealthStatus, PipelineStatus, RunOutcome } from "@/lib/api/types";

export type Tone = "ok" | "warn" | "bad" | "busy" | "idle" | "ink";

const TONES: Record<Tone, string> = {
  ok: "border-ok/25 bg-ok-soft text-ok",
  warn: "border-warn/25 bg-warn-soft text-warn",
  bad: "border-bad/25 bg-bad-soft text-bad",
  busy: "border-busy/25 bg-busy-soft text-busy",
  idle: "border-line-strong bg-bg-soft text-text-2",
  ink: "border-text bg-text text-bg",
};

export function Badge({
  tone = "idle",
  children,
  glyph,
  title,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  glyph?: ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[12px] font-medium leading-5",
        TONES[tone],
        className,
      )}
    >
      {glyph}
      {children}
    </span>
  );
}

const g = "size-3.5 shrink-0";

// -- Run status --------------------------------------------------------------

const STATUS: Record<PipelineStatus, { tone: Tone; label: string; glyph: ReactNode }> = {
  created: { tone: "idle", label: "Created", glyph: <CircleDashed aria-hidden="true" className={g} /> },
  initializing: { tone: "busy", label: "Initializing", glyph: <Loader2 aria-hidden="true" className={cx(g, "animate-spin")} /> },
  running: { tone: "busy", label: "Running", glyph: <Loader2 aria-hidden="true" className={cx(g, "animate-spin")} /> },
  completed: { tone: "ok", label: "Completed", glyph: <CheckCircle2 aria-hidden="true" className={g} /> },
  failed: { tone: "bad", label: "Failed", glyph: <XCircle aria-hidden="true" className={g} /> },
  cancelled: { tone: "idle", label: "Cancelled", glyph: <MinusCircle aria-hidden="true" className={g} /> },
  timed_out: { tone: "bad", label: "Timed out", glyph: <Clock aria-hidden="true" className={g} /> },
};

/** `pending` is the persisted status a listing can return for a created run. */
export function RunStatusBadge({ status }: { status: PipelineStatus | "pending" }) {
  const entry =
    status === "pending"
      ? STATUS.created
      : (STATUS[status] ?? { tone: "idle" as Tone, label: status, glyph: null });
  return (
    <Badge tone={entry.tone} glyph={entry.glyph}>
      {status === "pending" ? "Pending" : entry.label}
    </Badge>
  );
}

// -- Outcome -----------------------------------------------------------------

/**
 * Only `goal_achieved` is green. Several outcomes are findings about *us*
 * (`provider_error`, `audio_validation_failed`, `abandoned`), and colouring
 * them like a bot failure would misattribute the fault - so the hint says
 * whose side each is on.
 */
export const OUTCOME: Record<RunOutcome, { tone: Tone; label: string; hint: string }> = {
  goal_achieved: { tone: "ok", label: "Goal achieved", hint: "The caller reached its objective within the turn budget." },
  bot_refused: { tone: "warn", label: "Bot refused", hint: "The bot declined to help. A finding about the bot." },
  bot_unintelligible: { tone: "warn", label: "Bot unintelligible", hint: "The bot's replies could not be understood by the caller rules." },
  no_progress: { tone: "warn", label: "No progress", hint: "The conversation stopped advancing toward the objective." },
  turn_budget_exhausted: { tone: "warn", label: "Budget exhausted", hint: "The turn ceiling was reached before the objective was met." },
  provider_error: { tone: "bad", label: "Provider error", hint: "A speech provider failed. This is our side, not the bot's." },
  audio_validation_failed: { tone: "bad", label: "Audio invalid", hint: "Audio did not survive inspection. Not a statement about the bot." },
  external_bot_unavailable: { tone: "bad", label: "Bot unavailable", hint: "The bot adapter could not obtain a reply." },
  bot_protocol_error: { tone: "warn", label: "Bot protocol error", hint: "The bot answered outside its protocol. A finding about the bot's integration." },
  bot_ended_session: { tone: "warn", label: "Bot ended session", hint: "The bot closed the session before the caller reached its objective." },
  cancelled: { tone: "idle", label: "Cancelled", hint: "Stopped by an operator." },
  abandoned: {
    tone: "idle",
    label: "Abandoned",
    hint: "Left in flight with nothing executing it, then closed by stale-run recovery. Not a statement about the bot.",
  },
};

export function OutcomeBadge({ outcome }: { outcome: RunOutcome | null }) {
  if (outcome === null) {
    return <span className="text-[13px] text-text-3" title="An unfinished run has no result.">No result yet</span>;
  }
  const entry = OUTCOME[outcome] ?? { tone: "idle" as Tone, label: outcome, hint: "" };
  return (
    <Badge tone={entry.tone} title={entry.hint}>
      {entry.label}
    </Badge>
  );
}

// -- Execution mode ----------------------------------------------------------

/**
 * How much of the system a run exercised. Only `external_bot_test` may be
 * described as testing a voice bot, and even then the run's
 * `bot_audio_externally_received` has to agree - `RunEvidence` checks that.
 */
export const MODE_COPY: Record<ExecutionMode, { label: string; tone: Tone; hint: string }> = {
  offline_simulation: {
    label: "Offline simulation",
    tone: "idle",
    hint: "No audio moved. The caller's decisions were exercised, nothing else.",
  },
  audio_fixture_test: {
    label: "Fixture test",
    tone: "idle",
    hint: "Every stage ran with the bot stubbed by fixture audio. It establishes that the pipeline works, not that any bot does.",
  },
  external_bot_test: {
    label: "External voice bot",
    tone: "ink",
    hint: "Bot audio was supplied from outside this process. The only mode that may be described as testing a voice bot.",
  },
  text_bot_test: {
    label: "Text bot",
    tone: "ink",
    hint: "An external bot answered in text over HTTP. It tests what the bot says, and nothing about audio.",
  },
  telephony_test: {
    label: "Telephony",
    tone: "bad",
    hint: "Not implemented. No run can be created in this mode.",
  },
};

export function ModeBadge({ mode }: { mode: ExecutionMode }) {
  const entry = MODE_COPY[mode] ?? { label: mode, tone: "idle" as Tone, hint: "" };
  return (
    <Badge tone={entry.tone} title={entry.hint}>
      {entry.label}
    </Badge>
  );
}

// -- Verdict -----------------------------------------------------------------

export function VerdictBadge({ verdict }: { verdict: "pass" | "fail" | "undetermined" | null }) {
  if (verdict === null) {
    return (
      <Badge tone="idle" glyph={<CircleDashed aria-hidden="true" className={g} />} title="No evaluation has been stored for this run.">
        Not evaluated
      </Badge>
    );
  }
  const map = {
    pass: { tone: "ok" as Tone, label: "Pass", glyph: <CheckCircle2 aria-hidden="true" className={g} /> },
    fail: { tone: "bad" as Tone, label: "Fail", glyph: <XCircle aria-hidden="true" className={g} /> },
    undetermined: { tone: "warn" as Tone, label: "Undetermined", glyph: <CircleDot aria-hidden="true" className={g} /> },
  }[verdict];
  return (
    <Badge tone={map.tone} glyph={map.glyph}>
      {map.label}
    </Badge>
  );
}

// -- Availability and health -------------------------------------------------

export function AvailabilityBadge({ available, reason }: { available: boolean; reason?: string | null }) {
  return available ? (
    <Badge tone="ok" glyph={<CheckCircle2 aria-hidden="true" className={g} />} title="This deployment has what it needs to use it.">
      Available
    </Badge>
  ) : (
    <Badge tone="warn" glyph={<Ban aria-hidden="true" className={g} />} title={reason ?? undefined}>
      Not configured
    </Badge>
  );
}

export function HealthBadge({ status }: { status: HealthStatus }) {
  const map: Record<HealthStatus, { tone: Tone; label: string }> = {
    ok: { tone: "ok", label: "Healthy" },
    degraded: { tone: "warn", label: "Degraded" },
    unavailable: { tone: "bad", label: "Unavailable" },
  };
  const entry = map[status] ?? { tone: "idle" as Tone, label: status };
  return (
    <Badge tone={entry.tone} glyph={<span aria-hidden="true" className="size-1.5 rounded-full bg-current" />}>
      {entry.label}
    </Badge>
  );
}

/** A provider currently in use. Not a quality claim. */
export function SelectedBadge() {
  return <Badge tone="ink">In use</Badge>;
}
