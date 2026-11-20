/**
 * Every stage the pipeline ran, with its measured duration, grouped by the
 * turn index the backend recorded. Bars are relative to the slowest stage in
 * the run, so the figure is always printed beside the bar: a bar alone would
 * invite reading a ratio off the pixels.
 */

import { cx } from "@/components/ui/primitives";
import type { StageEvent } from "@/lib/api/types";
import { formatMs } from "@/lib/format";
import { describeBargeIn } from "@/lib/streaming";

const TONE: Record<string, string> = { ok: "bg-ok", failed: "bg-bad", skipped: "bg-idle", pending: "bg-busy" };
const WORD: Record<string, string> = { ok: "completed", failed: "failed", skipped: "skipped", pending: "pending" };

export function StageTimeline({ events }: { events: StageEvent[] }) {
  if (events.length === 0) {
    return <p className="px-4 py-8 text-center text-[13px] text-text-3">No stages ran. The run was created but never started.</p>;
  }
  const slowest = Math.max(...events.map((e) => e.duration_ms ?? 0), 1);
  const turns = [...new Set(events.map((e) => e.turn_index))].sort((a, b) => a - b);
  const total = events.reduce((n, e) => n + (e.duration_ms ?? 0), 0);
  return (
    <div>
      <p className="border-b border-line px-4 py-2.5 text-[12px] text-text-3 sm:px-5">
        {events.length} stages · {formatMs(total)} measured in total · bars relative to the slowest ({formatMs(slowest)})
      </p>
      <ol className="divide-y divide-line">
        {turns.map((turn) => (
          <li key={turn} className="px-4 py-3 sm:px-5">
            <p className="mb-2 font-mono text-[11px] uppercase tracking-[0.08em] text-text-3">Turn {turn}</p>
            <ul className="space-y-2">
              {events
                .filter((e) => e.turn_index === turn)
                .map((e, i) => {
                  const width = e.duration_ms === null ? 0 : Math.max(1.5, (e.duration_ms / slowest) * 100);
                  const barge = describeBargeIn(e.evidence ?? null);
                  return (
                    <li key={`${e.stage}-${i}`} className="grid grid-cols-[minmax(7.5rem,10rem)_minmax(0,1fr)_4.5rem] items-center gap-3">
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span aria-hidden="true" className={cx("size-1.5 shrink-0 rounded-full", TONE[e.status] ?? "bg-idle")} />
                        <span className="truncate font-mono text-[12px] text-text-2">{e.stage}</span>
                        <span className="sr-only">{WORD[e.status] ?? e.status}</span>
                      </span>
                      <span className="h-2 overflow-hidden rounded-full bg-bg-sunk">
                        <span className={cx("block h-full rounded-full", TONE[e.status] ?? "bg-idle")} style={{ width: `${width}%` }} />
                      </span>
                      <span className="text-right font-mono text-[12px] text-text-2 tabular">{formatMs(e.duration_ms) ?? "not timed"}</span>
                      {e.detail ? <span className="col-span-3 break-words text-[12px] leading-relaxed text-text-3">{e.detail}</span> : null}
                      {barge ? <span className="col-span-3 text-[12px] leading-relaxed text-text-2">{barge}</span> : null}
                    </li>
                  );
                })}
            </ul>
          </li>
        ))}
      </ol>
    </div>
  );
}
