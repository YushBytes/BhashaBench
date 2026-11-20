/**
 * Pass rate per group as a dot with its Wilson 95% interval.
 *
 * A dot plot, not bars: a pass rate from five runs and one from five hundred
 * look the same as bars and very different as intervals, and the interval is
 * the honest part. A group with no decided run has no dot and says so; it is
 * never drawn at zero. One series, so no legend: the title names it, and n is
 * printed on every row.
 */

import type { ReactNode } from "react";

export interface IntervalRow {
  key: string;
  label: ReactNode;
  rate: number | null;
  low: number | null;
  high: number | null;
  n: number;
}

const pct = (v: number) => `${Math.round(v * 100)}%`;

export function PassRateIntervals({ rows, caption }: { rows: IntervalRow[]; caption: string }) {
  return (
    <figure className="min-w-0">
      <figcaption className="sr-only">{caption}</figcaption>
      <div className="grid grid-cols-[minmax(6rem,11rem)_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-0">
        <span />
        <div aria-hidden="true" className="relative flex justify-between pb-2 font-mono text-[11px] text-text-3">
          <span>0%</span>
          <span>50%</span>
          <span>100%</span>
        </div>
        <span className="pb-2 text-right text-[11px] font-medium text-text-3">n</span>
        {rows.map((row) => (
          <div key={row.key} className="contents">
            <div className="min-w-0 truncate border-t border-line py-2.5 text-[13px] text-text">{row.label}</div>
            <div className="relative h-full border-t border-line py-2.5">
              <div aria-hidden="true" className="absolute inset-y-0 left-1/2 w-px bg-line" />
              {row.rate === null || row.low === null || row.high === null ? (
                <span className="relative text-[12px] text-text-3">No decided runs</span>
              ) : (
                <div
                  className="relative h-4"
                  title={`${pct(row.rate)} (95% interval ${pct(row.low)}–${pct(row.high)}), n = ${row.n}`}
                >
                  <span
                    aria-hidden="true"
                    className="absolute top-1/2 h-[2px] -translate-y-1/2 rounded-full bg-text-3"
                    style={{ left: `${row.low * 100}%`, width: `${Math.max((row.high - row.low) * 100, 0.5)}%` }}
                  />
                  <span
                    aria-hidden="true"
                    className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-text ring-2 ring-bg"
                    style={{ left: `${row.rate * 100}%` }}
                  />
                  <span className="sr-only">
                    {pct(row.rate)}, 95% interval {pct(row.low)} to {pct(row.high)}
                  </span>
                </div>
              )}
            </div>
            <div className="border-t border-line py-2.5 text-right font-mono text-[12px] text-text-2 tabular">{row.n}</div>
          </div>
        ))}
      </div>
    </figure>
  );
}
