"use client";

/**
 * Filters for the run history.
 *
 * A plain GET form, not controlled state. The filters end up in the URL, so
 * a filtered view can be shared, bookmarked and reloaded — which is most of
 * what filtering is for in an evidence tool. It also means the whole list
 * stays a server component and ships no data to the client.
 *
 * Native `<select>` deliberately: it is keyboard accessible for free and
 * becomes the platform picker on a phone, which no custom dropdown matches.
 */

import { useRouter } from "next/navigation";
import { useRef } from "react";

import { buttonClass, cx } from "@/components/ui/primitives";
import { RUN_MODES, RUN_OUTCOMES, RUN_STATUSES } from "@/lib/run-filters";

const field =
  "h-9 w-full rounded-md border border-line-strong bg-surface-raised px-2.5 " +
  "text-[13px] text-text transition-colors hover:border-[#3b4756] " +
  "focus-visible:border-accent";

const label = "block text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted";

export function RunFilters({
  current,
}: {
  current: Record<string, string | undefined>;
}) {
  const router = useRouter();
  const form = useRef<HTMLFormElement>(null);
  const active = Object.values(current).filter(Boolean).length;

  // Submitting the form navigates with the chosen parameters; empty fields
  // are dropped so the URL carries only what is actually filtered.
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const query = new URLSearchParams();
    for (const [key, value] of data.entries()) {
      const text = String(value).trim();
      if (text) query.set(key, text);
    }
    const qs = query.toString();
    router.push(qs ? `/app/runs?${qs}` : "/app/runs");
  }

  return (
    <form
      ref={form}
      onSubmit={submit}
      className="rounded-lg border border-line bg-surface p-3 sm:p-4"
      aria-label="Filter runs"
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <label className={label} htmlFor="filter-scenario">
            Scenario name
          </label>
          <input
            id="filter-scenario"
            name="scenario"
            type="search"
            defaultValue={current.scenario ?? ""}
            placeholder="Search by name"
            className={cx(field, "mt-1 placeholder:text-text-muted")}
          />
        </div>

        <div>
          <label className={label} htmlFor="filter-status">
            Status
          </label>
          <select
            id="filter-status"
            name="status"
            defaultValue={current.status ?? ""}
            className={cx(field, "mt-1")}
          >
            <option value="">Any</option>
            {RUN_STATUSES.map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={label} htmlFor="filter-mode">
            Mode
          </label>
          <select
            id="filter-mode"
            name="mode"
            defaultValue={current.mode ?? ""}
            className={cx(field, "mt-1")}
          >
            <option value="">Any</option>
            {RUN_MODES.map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={label} htmlFor="filter-outcome">
            Outcome
          </label>
          <select
            id="filter-outcome"
            name="outcome"
            defaultValue={current.outcome ?? ""}
            className={cx(field, "mt-1")}
          >
            <option value="">Any</option>
            {RUN_OUTCOMES.map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="submit" className={buttonClass("default", "sm")}>
          Apply
        </button>
        {active > 0 ? (
          <button
            type="button"
            onClick={() => router.push("/app/runs")}
            className={buttonClass("quiet", "sm")}
          >
            Clear {active} filter{active === 1 ? "" : "s"}
          </button>
        ) : null}
      </div>
    </form>
  );
}
