"use client";

/**
 * Runs per period, stacked by their latest verdict.
 *
 * The four segments are statuses, not series, so they use the reserved
 * status colours - validated with the dataviz skill's checker in this order:
 * pass, undetermined, fail, with red and green never adjacent (they collapse
 * under deuteranopia). Fail also carries a hatch, a second encoding that
 * survives greyscale and forced colours. "Not evaluated" is grey on purpose:
 * it is an absence, not a result.
 *
 * Every bar has a hover and focus tooltip with its counts, and the same data
 * is one click away as a table. Bars are relative to the busiest period,
 * which is why the axis states its maximum.
 */

import { useId, useState } from "react";

import { cx } from "@/components/ui/primitives";
import { DISPLAY_LOCALE } from "@/lib/format";

export interface TrendPeriod {
  period: string;
  runs: number;
  verdicts: { pass: number; fail: number; undetermined: number; not_evaluated: number };
}

const SEGMENTS = [
  { key: "pass", label: "Pass", className: "bg-[#13804a]" },
  { key: "undetermined", label: "Undetermined", className: "bg-[#d98a1c]" },
  {
    key: "fail",
    label: "Fail",
    className: "bg-[#c1121f] bg-[repeating-linear-gradient(135deg,transparent_0_3px,rgb(255_255_255/0.35)_3px_5px)]",
  },
  { key: "not_evaluated", label: "Not evaluated", className: "bg-[#c4c4cc]" },
] as const;

function label(period: string): string {
  const date = new Date(`${period.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(date.getTime())
    ? period.slice(0, 10)
    : new Intl.DateTimeFormat(DISPLAY_LOCALE, { month: "short", day: "numeric", timeZone: "UTC" }).format(date);
}

export function VerdictTrend({ periods, title = "Runs per day by verdict" }: { periods: TrendPeriod[]; title?: string }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const [hover, setHover] = useState<number | null>(null);
  const titleId = useId();
  const max = Math.max(1, ...periods.map((p) => p.runs));
  const ticks = [max, Math.round(max / 2), 0].filter((v, i, all) => all.indexOf(v) === i);

  return (
    <figure aria-labelledby={titleId} className="min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <figcaption id={titleId} className="text-[13px] font-medium text-text">
          {title}
        </figcaption>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <ul className="flex flex-wrap items-center gap-x-3 gap-y-1" aria-label="Legend">
            {SEGMENTS.map((segment) => (
              <li key={segment.key} className="flex items-center gap-1.5 text-[12px] text-text-2">
                <span aria-hidden="true" className={cx("size-2.5 rounded-[3px]", segment.className)} />
                {segment.label}
              </li>
            ))}
          </ul>
          <div role="group" aria-label="View" className="flex rounded-md border border-line p-0.5">
            {(["chart", "table"] as const).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => setView(v)}
                className={cx(
                  "h-7 rounded px-2.5 text-[12px] font-medium capitalize",
                  view === v ? "bg-bg-sunk text-text" : "text-text-3 hover:text-text",
                )}
              >
                {v}
              </button>
            ))}
          </div>
        </div>
      </div>

      {view === "table" ? (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-max text-left text-[13px]">
            <thead>
              <tr className="border-b border-line text-[12px] text-text-3">
                <th scope="col" className="py-2 pr-4 font-medium">Day (UTC)</th>
                <th scope="col" className="py-2 pr-4 text-right font-medium">Runs</th>
                {SEGMENTS.map((s) => (
                  <th key={s.key} scope="col" className="py-2 pr-4 text-right font-medium">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {periods.map((p) => (
                <tr key={p.period} className="border-b border-line last:border-0">
                  <td className="py-2 pr-4 font-mono text-text-2">{p.period.slice(0, 10)}</td>
                  <td className="py-2 pr-4 text-right font-mono tabular">{p.runs}</td>
                  {SEGMENTS.map((s) => (
                    <td key={s.key} className="py-2 pr-4 text-right font-mono tabular text-text-2">
                      {p.verdicts[s.key]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3">
          <div className="flex h-44 flex-col justify-between pb-0 text-right font-mono text-[11px] text-text-3 tabular" aria-hidden="true">
            {ticks.map((tick) => (
              <span key={tick} className="-translate-y-1/2 first:translate-y-0 last:translate-y-0">
                {tick}
              </span>
            ))}
          </div>
          <div className="relative h-44 min-w-0">
            <div aria-hidden="true" className="pointer-events-none absolute inset-0 flex flex-col justify-between">
              {ticks.map((tick) => (
                <span key={tick} className="h-px w-full bg-line" />
              ))}
            </div>
            <ol className="relative flex h-full items-end gap-[3px] sm:gap-1.5" aria-label="Runs per day">
              {periods.map((p, index) => {
                const parts = SEGMENTS.map((s) => ({ ...s, value: p.verdicts[s.key] })).filter((s) => s.value > 0);
                const summary = `${label(p.period)}: ${p.runs} run${p.runs === 1 ? "" : "s"} — ${parts
                  .map((s) => `${s.value} ${s.label.toLowerCase()}`)
                  .join(", ")}`;
                return (
                  <li
                    key={p.period}
                    tabIndex={0}
                    aria-label={summary}
                    onMouseEnter={() => setHover(index)}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(index)}
                    onBlur={() => setHover(null)}
                    className="group relative flex h-full min-w-0 max-w-12 flex-1 cursor-default flex-col justify-end rounded-sm outline-offset-2"
                  >
                    <div
                      className="flex flex-col-reverse gap-[2px] overflow-hidden rounded-t-[4px] transition-opacity"
                      style={{ height: `${(p.runs / max) * 100}%`, opacity: hover === null || hover === index ? 1 : 0.45 }}
                    >
                      {parts.map((s) => (
                        <span key={s.key} className={s.className} style={{ flexGrow: s.value, minHeight: 2 }} />
                      ))}
                    </div>
                    {hover === index ? (
                      <div
                        role="tooltip"
                        className={cx(
                          "pointer-events-none absolute bottom-full z-10 mb-2 w-max min-w-36 rounded-md border border-line bg-bg px-3 py-2 shadow-pop",
                          index > periods.length / 2 ? "right-0" : "left-0",
                        )}
                      >
                        <p className="text-[12px] font-medium text-text">{label(p.period)}</p>
                        <p className="font-mono text-[12px] text-text-2 tabular">{p.runs} runs</p>
                        <ul className="mt-1 space-y-0.5">
                          {SEGMENTS.map((s) => (
                            <li key={s.key} className="flex items-center gap-1.5 text-[12px] text-text-2">
                              <span aria-hidden="true" className={cx("size-2 rounded-[2px]", s.className)} />
                              <span className="flex-1">{s.label}</span>
                              <span className="font-mono tabular">{p.verdicts[s.key]}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </div>
          <span />
          <div className="mt-2 flex justify-between font-mono text-[11px] text-text-3" aria-hidden="true">
            <span>{periods[0] ? label(periods[0].period) : ""}</span>
            {periods.length > 2 ? <span>{label(periods[Math.floor(periods.length / 2)].period)}</span> : null}
            <span>{periods.length > 1 ? label(periods[periods.length - 1].period) : ""}</span>
          </div>
        </div>
      )}
    </figure>
  );
}
