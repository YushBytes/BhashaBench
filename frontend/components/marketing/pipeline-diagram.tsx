import { cx } from "@/components/ui/primitives";

/**
 * The hero's product demonstration.
 *
 * A diagram of the pipeline, not a screenshot of a dashboard and not a
 * mock chart. Every label is a real stage name from
 * `app/pipeline/engine.py`, every provider named is one that is actually
 * wired up, and the two marked as absent are absent. It is drawn as a
 * diagram precisely so nobody can mistake it for captured output — there
 * are no numbers on it to misread.
 */

const STAGES = [
  { id: "caller_turn", label: "Caller decides", by: "rule engine", tone: "accent" },
  { id: "caller_synthesis", label: "Speech synthesised", by: "Timbre", tone: "accent" },
  { id: "degradation", label: "Conditions applied", by: "degradation", tone: "accent" },
  { id: "bot_exchange", label: "Bot replies", by: "adapter", tone: "alt" },
  { id: "bot_audio_validation", label: "Audio validated", by: "pipeline", tone: "alt" },
  { id: "bot_transcription", label: "Reply transcribed", by: "Prisma", tone: "alt" },
] as const;

export function PipelineDiagram() {
  return (
    <figure className="rounded-xl border border-line bg-surface p-4 sm:p-5">
      <figcaption className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[13px] font-semibold text-text">One turn of a run</span>
        <span className="font-mono text-[11px] text-text-muted">
          six stages, each timed
        </span>
      </figcaption>

      <ol className="space-y-1.5">
        {STAGES.map((stage, index) => (
          <li
            key={stage.id}
            className="grid grid-cols-[1.25rem_minmax(0,1fr)] items-center gap-3"
          >
            <span className="flex h-full flex-col items-center">
              <span
                aria-hidden="true"
                className={cx(
                  "size-2 shrink-0 rounded-full",
                  stage.tone === "accent" ? "bg-accent" : "bg-accent-alt",
                )}
              />
              {index < STAGES.length - 1 ? (
                <span aria-hidden="true" className="mt-1 w-px flex-1 bg-line-strong" />
              ) : null}
            </span>

            <span className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 rounded-md border border-line bg-surface-raised px-3 py-2">
              <span className="text-[13px] text-text">{stage.label}</span>
              <span className="font-mono text-[11px] text-text-muted">{stage.by}</span>
            </span>
          </li>
        ))}
      </ol>

      <p className="mt-4 border-t border-line pt-3 text-[12px] leading-relaxed text-text-muted">
        The loop repeats until the caller reaches its objective or the turn
        budget ends it. Both audio files for every turn — before and after
        degradation — are kept, so a result can be listened to rather than
        taken on trust.
      </p>
    </figure>
  );
}
