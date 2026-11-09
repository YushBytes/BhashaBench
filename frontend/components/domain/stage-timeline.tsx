import { cx } from "@/components/ui/primitives";
import { formatMs } from "@/lib/format";
import type { StageEvent } from "@/lib/api/types";

/**
 * Every stage the pipeline ran, with its measured duration.
 *
 * A rail rather than a chart: there are six stage kinds and a handful of
 * turns, so a bar per event reads faster than any plotting library would,
 * costs nothing on the client, and keeps the duration a number rather than
 * a length the reader has to estimate.
 *
 * Bar widths are relative to the slowest event in the run, which is why the
 * figure is always printed beside the bar. A bar alone would invite reading
 * a ratio off the pixels.
 */

const STATUS_TONE: Record<string, string> = {
  ok: "bg-ok",
  failed: "bg-bad",
  skipped: "bg-idle",
  pending: "bg-busy",
};

const STATUS_LABEL: Record<string, string> = {
  ok: "completed",
  failed: "failed",
  skipped: "skipped",
  pending: "pending",
};

export function StageTimeline({ events }: { events: StageEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="px-4 py-6 text-[13px] text-text-dim">
        No stages ran. This run was created but never started.
      </p>
    );
  }

  const slowest = Math.max(
    ...events.map((event) => event.duration_ms ?? 0),
    1,
  );

  // Group by turn so the rail reads as a conversation rather than a flat log.
  const turns = [...new Set(events.map((event) => event.turn_index))].sort(
    (a, b) => a - b,
  );

  return (
    <ol className="divide-y divide-line">
      {turns.map((turnIndex) => (
        <li key={turnIndex} className="px-4 py-3">
          <p className="mb-2 font-mono text-[11px] uppercase tracking-[0.08em] text-text-muted">
            Turn {turnIndex}
          </p>
          <ul className="space-y-1.5">
            {events
              .filter((event) => event.turn_index === turnIndex)
              .map((event, index) => {
                const ms = formatMs(event.duration_ms);
                const width =
                  event.duration_ms === null
                    ? 0
                    : Math.max(2, (event.duration_ms / slowest) * 100);
                return (
                  <li
                    key={`${event.stage}-${index}`}
                    className="grid grid-cols-[minmax(7rem,1fr)_minmax(0,2fr)_auto] items-center gap-3"
                  >
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span
                        aria-hidden="true"
                        className={cx(
                          "inline-block size-1.5 shrink-0 rounded-full",
                          STATUS_TONE[event.status] ?? "bg-idle",
                        )}
                      />
                      <span className="truncate font-mono text-[12px] text-text-dim">
                        {event.stage}
                      </span>
                      <span className="sr-only">
                        {STATUS_LABEL[event.status] ?? event.status}
                      </span>
                    </span>

                    <span className="h-1.5 w-full overflow-hidden rounded-full bg-surface-raised">
                      <span
                        className={cx(
                          "block h-full rounded-full",
                          STATUS_TONE[event.status] ?? "bg-idle",
                        )}
                        style={{ width: `${width}%` }}
                      />
                    </span>

                    <span className="whitespace-nowrap text-right font-mono text-[11px] tabular text-text-muted">
                      {ms ?? "not timed"}
                    </span>

                    {event.detail ? (
                      <span className="col-span-3 text-[12px] leading-relaxed text-text-dim">
                        {event.detail}
                      </span>
                    ) : null}
                  </li>
                );
              })}
          </ul>
        </li>
      ))}
    </ol>
  );
}
