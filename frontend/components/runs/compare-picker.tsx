"use client";

/**
 * Pick a baseline and a candidate run by searching what you remember about
 * them - scenario, language, mode, date - rather than by pasting ids.
 * Comparison is pairwise: exactly two runs, which is what the API compares.
 */

import { useRouter } from "next/navigation";
import { useId, useMemo, useState } from "react";
import { ArrowLeftRight, GitCompareArrows, Search } from "lucide-react";

import { controlClass } from "@/components/ui/field";
import { Button, cx } from "@/components/ui/primitives";

export interface PickableRun {
  id: string;
  label: string;
  detail: string;
}

function Picker({
  label,
  runs,
  value,
  onChange,
  exclude,
}: {
  label: string;
  runs: PickableRun[];
  value: string;
  onChange: (id: string) => void;
  exclude: string;
}) {
  const id = useId();
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return runs.filter((r) => r.id !== exclude && (!q || `${r.label} ${r.detail} ${r.id}`.toLowerCase().includes(q)));
  }, [runs, query, exclude]);
  const selected = runs.find((r) => r.id === value);
  return (
    <div className="min-w-0">
      <label htmlFor={`${id}-search`} className="text-[13px] font-medium text-text">
        {label}
      </label>
      <div className="relative mt-1.5">
        <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-text-3" />
        <input
          id={`${id}-search`}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search scenario, language, mode or date"
          aria-controls={`${id}-list`}
          className={cx(controlClass, "h-9 pl-8")}
        />
      </div>
      <select
        id={`${id}-list`}
        aria-label={`${label} run`}
        size={6}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-2 block w-full rounded-md border border-line-strong bg-bg p-1 text-[13px] text-text"
      >
        {shown.map((r) => (
          <option key={r.id} value={r.id} className="rounded px-2 py-1.5">
            {r.label} — {r.detail}
          </option>
        ))}
      </select>
      <p className="mt-1.5 min-h-5 text-[12px] text-text-3">
        {selected ? (
          <>
            Selected: <span className="font-medium text-text-2">{selected.label}</span> · <span className="font-mono">{selected.id.slice(0, 8)}</span>
          </>
        ) : shown.length === 0 ? (
          "Nothing matches."
        ) : (
          "None selected."
        )}
      </p>
    </div>
  );
}

export function ComparePicker({ runs, baseline, candidate }: { runs: PickableRun[]; baseline?: string; candidate?: string }) {
  const router = useRouter();
  const [a, setA] = useState(baseline ?? runs[1]?.id ?? "");
  const [b, setB] = useState(candidate ?? runs[0]?.id ?? "");
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] lg:items-start">
        <Picker label="Baseline" runs={runs} value={a} onChange={setA} exclude={b} />
        <Button
          tone="ghost"
          size="sm"
          className="justify-self-center lg:mt-9"
          onClick={() => {
            setA(b);
            setB(a);
          }}
        >
          <ArrowLeftRight aria-hidden="true" className="size-4" />
          Swap
        </Button>
        <Picker label="Candidate" runs={runs} value={b} onChange={setB} exclude={a} />
      </div>
      <Button tone="primary" disabled={!a || !b || a === b} onClick={() => router.push(`/app/compare?baseline=${a}&candidate=${b}`)}>
        <GitCompareArrows aria-hidden="true" className="size-4" />
        Compare these two runs
      </Button>
    </div>
  );
}
