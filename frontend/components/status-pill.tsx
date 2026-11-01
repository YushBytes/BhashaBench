import { statusLabel, type Status } from "@/lib/content";

const styles: Record<Status, string> = {
  live: "border-status-live/30 bg-status-live/10 text-status-live",
  partial: "border-status-partial/30 bg-status-partial/10 text-status-partial",
  planned: "border-border-strong bg-surface-overlay text-text-tertiary",
};

interface StatusPillProps {
  readonly status: Status;
  /** Overrides the default label, e.g. "Planned · Phase 7". */
  readonly label?: string;
}

/**
 * A small status chip. The colour vocabulary is fixed in `globals.css` so
 * "live" always means verified-working and never decorates something planned.
 */
export function StatusPill({ status, label }: StatusPillProps) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${styles[status]}`}
    >
      <span
        aria-hidden="true"
        className="size-1.5 rounded-full bg-current opacity-80"
      />
      {label ?? statusLabel[status]}
    </span>
  );
}
