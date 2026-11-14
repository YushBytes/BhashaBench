/**
 * The status vocabulary.
 *
 * The Phase 8 audit found one `StatusPill` carrying four different meanings
 * across the old page. These are deliberately separate components: a run
 * status, an outcome, an execution mode and a provider's availability are
 * different statements, and a reader who learns one badge should not have to
 * re-learn it on the next screen.
 *
 * **No status is colour alone.** Every badge pairs its hue with a word, and
 * the run-status badge with a glyph, so the table reads correctly in
 * greyscale and to anyone who cannot separate the hues.
 */

import type { ReactNode } from "react";

import { cx } from "./primitives";
import type {
  ExecutionMode,
  HealthStatus,
  PipelineStatus,
  RunOutcome,
} from "@/lib/api/types";

type Tone = "ok" | "warn" | "bad" | "busy" | "idle" | "accent";

const TONES: Record<Tone, string> = {
  ok: "border-ok/30 bg-ok-dim text-ok",
  warn: "border-warn/30 bg-warn-dim text-warn",
  bad: "border-bad/30 bg-bad-dim text-bad",
  busy: "border-busy/30 bg-busy-dim text-busy",
  idle: "border-line-strong bg-idle-dim text-text-dim",
  accent: "border-accent-line bg-accent-dim text-accent",
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
        "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full",
        "border px-2 py-0.5 text-[11px] font-medium",
        TONES[tone],
        className,
      )}
    >
      {glyph}
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Run status
// ---------------------------------------------------------------------------

const STATUS: Record<PipelineStatus, { tone: Tone; label: string }> = {
  created: { tone: "idle", label: "Created" },
  initializing: { tone: "busy", label: "Initializing" },
  running: { tone: "busy", label: "Running" },
  completed: { tone: "ok", label: "Completed" },
  failed: { tone: "bad", label: "Failed" },
  cancelled: { tone: "idle", label: "Cancelled" },
  timed_out: { tone: "bad", label: "Timed out" },
};

export function RunStatusBadge({ status }: { status: PipelineStatus }) {
  const { tone, label } = STATUS[status] ?? { tone: "idle" as Tone, label: status };
  const live = status === "running" || status === "initializing";
  return (
    <Badge
      tone={tone}
      glyph={
        <span
          aria-hidden="true"
          className={cx(
            "inline-block size-1.5 shrink-0 rounded-full bg-current",
            live && "bb-live-dot",
          )}
        />
      }
    >
      {label}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Outcome
// ---------------------------------------------------------------------------

/**
 * What the run established.
 *
 * Only `goal_achieved` is green. Every other outcome is a finding rather
 * than a success, and several are findings about *us* rather than the bot:
 * `provider_error` and `audio_validation_failed` say our pipeline broke, and
 * colouring them like a bot failure would misattribute the fault.
 */
const OUTCOME: Record<RunOutcome, { tone: Tone; label: string; hint: string }> = {
  goal_achieved: {
    tone: "ok",
    label: "Goal achieved",
    hint: "The caller reached its objective within the turn budget.",
  },
  bot_refused: {
    tone: "warn",
    label: "Bot refused",
    hint: "The bot declined to help. A finding about the bot.",
  },
  bot_unintelligible: {
    tone: "warn",
    label: "Bot unintelligible",
    hint: "The bot's replies could not be understood by the caller rules.",
  },
  no_progress: {
    tone: "warn",
    label: "No progress",
    hint: "The conversation stopped advancing toward the objective.",
  },
  turn_budget_exhausted: {
    tone: "warn",
    label: "Budget exhausted",
    hint: "The turn ceiling was reached before the objective was met.",
  },
  provider_error: {
    tone: "bad",
    label: "Provider error",
    hint: "A speech provider failed. This is our side, not the bot's.",
  },
  audio_validation_failed: {
    tone: "bad",
    label: "Audio invalid",
    hint: "Audio did not survive inspection. Not a statement about the bot.",
  },
  external_bot_unavailable: {
    tone: "bad",
    label: "Bot unavailable",
    hint: "The bot adapter could not obtain a reply.",
  },
  cancelled: {
    tone: "idle",
    label: "Cancelled",
    hint: "Stopped by an operator.",
  },
  abandoned: {
    tone: "idle",
    label: "Abandoned",
    hint: "Left in flight with nothing executing it, then closed by stale-run recovery. Not a statement about the bot.",
  },
};

export function OutcomeBadge({ outcome }: { outcome: RunOutcome | null }) {
  if (outcome === null) {
    return (
      <span className="text-[13px] text-text-muted" title="An unfinished run has no result.">
        —
      </span>
    );
  }
  const entry = OUTCOME[outcome] ?? {
    tone: "idle" as Tone,
    label: outcome,
    hint: "",
  };
  return (
    <Badge tone={entry.tone} title={entry.hint}>
      {entry.label}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Execution mode
// ---------------------------------------------------------------------------

/**
 * How much of the system a run actually exercised.
 *
 * The mode is the honesty control, so the badge says what the run touched
 * rather than only naming the mode. Only `external_bot_test` may be
 * described as testing a bot, and even then the run's
 * `bot_audio_externally_received` has to agree - which is what
 * `EvidenceNotice` checks.
 */
export const MODE_COPY: Record<
  ExecutionMode,
  { label: string; tone: Tone; hint: string }
> = {
  offline_simulation: {
    label: "Offline simulation",
    tone: "idle",
    hint: "No audio moved. The caller's decisions were exercised, nothing else.",
  },
  audio_fixture_test: {
    label: "Fixture test",
    tone: "idle",
    hint:
      "Every stage ran with the bot stubbed by fixture audio. It establishes " +
      "that the pipeline works, not that any bot does.",
  },
  external_bot_test: {
    label: "External bot",
    tone: "accent",
    hint:
      "Bot audio was supplied from outside this process. The only mode that " +
      "may be described as testing a bot.",
  },
  telephony_test: {
    label: "Telephony",
    tone: "bad",
    hint: "Not implemented. No run can be created in this mode.",
  },
};

export function ModeBadge({ mode }: { mode: ExecutionMode }) {
  const entry = MODE_COPY[mode] ?? {
    label: mode,
    tone: "idle" as Tone,
    hint: "",
  };
  return (
    <Badge tone={entry.tone} title={entry.hint}>
      {entry.label}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Health and availability
// ---------------------------------------------------------------------------

const HEALTH: Record<HealthStatus, { tone: Tone; label: string }> = {
  ok: { tone: "ok", label: "Healthy" },
  degraded: { tone: "warn", label: "Degraded" },
  unavailable: { tone: "bad", label: "Unavailable" },
};

export function HealthBadge({ status }: { status: HealthStatus }) {
  const entry = HEALTH[status] ?? { tone: "idle" as Tone, label: status };
  return <Badge tone={entry.tone}>{entry.label}</Badge>;
}

/**
 * Whether a provider can currently be built, and why not when it cannot.
 *
 * `selected` and `available` are different questions: a provider can be
 * configured and missing its credential, and the operator needs to see both
 * rather than one standing in for the other.
 */
export function AvailabilityBadge({
  available,
  reason,
}: {
  available: boolean;
  reason?: string | null;
}) {
  return available ? (
    <Badge tone="ok">Available</Badge>
  ) : (
    <Badge tone="bad" title={reason ?? undefined}>
      Unavailable
    </Badge>
  );
}

/**
 * Marks the provider the server is actually configured to use.
 *
 * Load-bearing when the selection is a test double: a run executed against
 * the `fake` provider establishes nothing, and that has to be visible
 * without opening the configuration.
 */
export function SelectedBadge({ name }: { name: string }) {
  const isFake = name === "fake";
  return (
    <Badge
      tone={isFake ? "warn" : "accent"}
      title={
        isFake
          ? "The configured provider is the offline test double. Its output is scripted, not recognised."
          : "The provider this server is configured to use."
      }
    >
      {isFake ? "Selected · test double" : "Selected"}
    </Badge>
  );
}
