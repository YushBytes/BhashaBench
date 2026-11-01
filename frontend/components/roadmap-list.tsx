import { StatusPill } from "@/components/status-pill";
import { phases } from "@/lib/content";

/** All 15 phases with their real status. Only Phase 1 is marked live. */
export function RoadmapList() {
  return (
    <ol className="overflow-hidden rounded-xl border border-border-subtle">
      {phases.map((phase, index) => (
        <li
          key={phase.number}
          className={`flex items-center gap-4 px-4 py-3 sm:px-5 ${
            index % 2 === 0 ? "bg-surface-raised" : "bg-surface-base"
          }`}
        >
          <span className="w-7 shrink-0 font-mono text-xs text-text-tertiary">
            {String(phase.number).padStart(2, "0")}
          </span>
          <span
            className={`flex-1 text-sm ${
              phase.status === "live"
                ? "font-medium text-text-primary"
                : "text-text-secondary"
            }`}
          >
            {phase.title}
          </span>
          <StatusPill
            status={phase.status}
            label={phase.status === "live" ? "Complete" : undefined}
          />
        </li>
      ))}
    </ol>
  );
}
